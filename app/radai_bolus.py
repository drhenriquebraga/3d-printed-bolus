# -*- coding: utf-8 -*-

import math
import os
import struct
import time

import numpy as np


try:
    import radai_skin as _skin
    LIMIAR_HU = float(_skin.LIMIAR_AR_HU)
except Exception:
    _skin = None
    LIMIAR_HU = -300.0

_HU_BLOQUEADO = 400.0
_HU_POR_MM = 700.0

MODOS = ("anatomico", "caixa")
DIRECOES = ("ant", "post", "dir", "esq", "sup", "inf")

_NORMAL = {"ant": (1, -1), "post": (1, 1), "dir": (0, -1), "esq": (0, 1),
           "sup": (2, 1), "inf": (2, -1)}
_CIMA = {"ant": (2, 1), "post": (2, 1), "dir": (2, 1), "esq": (2, 1),
         "sup": (1, -1), "inf": (1, -1)}

ESPESSURA_MIN_MM = 1
ESPESSURA_MAX_MM = 30
ESPESSURA_PADRAO_MM = 5
SUAVIZACAO_MAX_MM = 10.0

CASCA_MIN_MM = 1
CASCA_MAX_MM = 4
CASCA_PADRAO_MM = 2
ABERTURAS = ("externa", "superior", "inferior", "esquerda", "direita")
ABERTURA_PADRAO = "superior"
_ABERTURA_EIXO = {"superior": (2, 1), "inferior": (2, -1),
                  "esquerda": (0, 1), "direita": (0, -1)}
_CASCA_POR_GRADE = math.sqrt(3.0)
VIZINHOS_DA_DISTANCIA = 16
BLOCO_DISTANCIA = 12000
FRAGMENTO_MAX_FRACAO = 0.05
FAIXA_POR_BLOCO = 400000
MEDIDAS_DA_CASCA = 150000
TETO_MOLDE_VOXELS = 4000000
CABECALHO_STL_MOLDE = (b"RadAI Bolus MOLD cavity=bolus | DRAFT UNAPPROVED | "
                       b"physics+MD review | mm LPS")

GRADES_MM = (0.5, 0.75, 1.0)
TETO_VOXELS = 8000000
ORCAMENTO_PICO_MIB = 400
TETO_POR_GRADE = {0.5: 1000000, 0.75: 2000000, 1.0: TETO_VOXELS}
TETO_PREVIA = 4000000
PREVIA_MIN_MM = 1.5
CAIXA_MIN_MM = 10.0

CELULA_MM = 2.0
RELEVO_MM = 1.5

RENTE_POR_GRADE = 1e-3

ALERTA = (u"Não é para uso clínico. A densidade varia com o filamento, e a "
          u"dosimetria do material é obrigatória para avaliar a atenuação.")
FRASE_DO_ATO = (u"Declaro que este STL é um rascunho sujeito a revisão física "
                u"e médica, que não é para uso clínico, e que a atenuação do "
                u"material será medida antes de qualquer uso.")
AVISO_BIOMETRIA = (u"A face interna deste bólus é a superfície da pele do "
                   u"paciente. Num bólus de cabeça ou face, o arquivo é uma "
                   u"biometria: trate-o como dado de paciente.")

CABECALHO_STL = (b"RadAI 3D Printed Bolus | DRAFT UNAPPROVED | physics+MD "
                 b"review | mm LPS")

_DTYPE_STL = np.dtype([("n", "<f4", (3,)), ("v", "<f4", (3, 3)),
                       ("a", "<u2")])


class Recusa(ValueError):
    pass



def conferir_modalidade(modalidade):
    m = str(modalidade or u"").strip().upper()
    if m == u"CT":
        return True
    if m in (u"MR", u"MRI"):
        raise Recusa(u"RM recusada: sem Hounsfield não há pele a medir, e a "
                     u"distorção geométrica fica na borda do campo. Use uma "
                     u"TC diagnóstica recente.")
    raise Recusa(u"Só tomografia: modalidade %s não serve para bólus."
                 % (m or u"desconhecida"))


TETO_SERIE_VOXELS = 512 * 512 * 600
_HU_PISO, _HU_TETO = -1024.0, 32000.0


def conferir_tamanho_da_serie(voxels):
    try:
        v = int(voxels)
    except Exception:
        return True
    if v > TETO_SERIE_VOXELS:
        raise Recusa(u"Série grande demais para o bólus: %.0f milhões de "
                     u"voxels, e o teto é %.0f milhões (600 cortes de "
                     u"512 × 512). Use a reconstrução mais grossa do mesmo "
                     u"exame." % (v / 1e6, TETO_SERIE_VOXELS / 1e6))
    return True


def _int16_lps(img):
    import SimpleITK as sitk
    precisa = img.GetPixelID() != sitk.sitkInt16
    if not precisa:
        mm = sitk.MinimumMaximumImageFilter()
        mm.Execute(img)
        precisa = mm.GetMinimum() < _HU_PISO or mm.GetMaximum() > _HU_TETO
    if precisa:
        img = sitk.Clamp(img, sitk.sitkInt16, _HU_PISO, _HU_TETO)
    o = sitk.DICOMOrientImageFilter.GetOrientationFromDirectionCosines(
        img.GetDirection())
    if o == "LPS":
        return img
    if o[0] in "LR" and o[1] in "PA" and o[2] in "SI":
        f = sitk.Flip(img, [o[0] == "R", o[1] == "A", o[2] == "I"])
        if sitk.DICOMOrientImageFilter.GetOrientationFromDirectionCosines(
                f.GetDirection()) == "LPS":
            return f
    return sitk.DICOMOrient(img, "LPS")


class Serie(object):

    def __init__(self, img):
        import SimpleITK as sitk
        o = _int16_lps(img)
        self.img = o
        self.hu = sitk.GetArrayViewFromImage(o)
        self.esp = np.array(o.GetSpacing(), dtype=np.float64)
        self.origem = np.array(o.GetOrigin(), dtype=np.float64)
        self.D = np.array(o.GetDirection(), dtype=np.float64).reshape(3, 3)
        self.forma = tuple(int(v) for v in o.GetSize())
        self.extensao = (np.array(self.forma) - 1) * self.esp
        self.previa = None

    def quadro_para_lps(self, mm_xyz):
        p = np.asarray(mm_xyz, dtype=np.float64).reshape(-1, 3)
        return self.origem[None, :] + p.dot(self.D.T)

    def lps_para_quadro(self, lps):
        p = np.asarray(lps, dtype=np.float64).reshape(-1, 3)
        return (p - self.origem[None, :]).dot(self.D)


def abrir(img, modalidade="CT"):
    conferir_modalidade(modalidade)
    if callable(img):
        img = img()
    conferir_tamanho_da_serie(img.GetNumberOfPixels())
    img = _int16_lps(img)
    s = Serie(img)
    del img
    s.previa = previa_do_corpo(s)
    return s


def previa_do_corpo(serie):
    import SimpleITK as sitk
    ext = serie.extensao + serie.esp
    vol = float(np.prod(ext))
    c = max(PREVIA_MIN_MM, (vol / float(TETO_PREVIA)) ** (1.0 / 3.0))
    forma = [max(2, int(math.floor(ext[i] / c)) + 1) for i in range(3)]
    grossa = sitk.Resample(serie.img, forma, sitk.Transform(),
                           sitk.sitkLinear, serie.img.GetOrigin(), (c, c, c),
                           serie.img.GetDirection(), -1000.0,
                           sitk.sitkFloat32)
    hu = sitk.GetArrayFromImage(grossa)
    corpo = None
    if _skin is not None:
        try:
            import radai_geom
            corpo = _skin.contorno_externo(hu, radai_geom.Grade((c, c, c)))
        except Exception:
            corpo = None
    cru = corpo is None
    if cru:
        corpo = hu > LIMIAR_HU
    from scipy import ndimage
    perto = ndimage.binary_dilation(corpo, iterations=2)
    hu_desenho = ndimage.gaussian_filter(hu, 0.7)
    dens = np.clip(np.round(128.0 + (hu_desenho - LIMIAR_HU) *
                            (127.0 / 400.0)), 0, 255).astype(np.uint8)
    del hu_desenho
    dens[~perto] = 0
    return {"mask": np.ascontiguousarray(corpo.astype(np.uint8)), "sp": c,
            "densidade": np.ascontiguousarray(dens),
            "off": [0.0, 0.0, 0.0], "forma": forma, "sem_mesa": not cru}


def densidade_do_campo(F):
    return np.ascontiguousarray(np.clip(np.floor(128.0 - np.asarray(
        F, dtype=np.float32) * 64.0), 0, 255).astype(np.uint8))


def normalizar_caixa(serie, caixa):
    try:
        v = [float(caixa[k]) for k in ("x0", "x1", "y0", "y1", "z0", "z1")]
    except Exception:
        raise Recusa(u"Caixa inválida: faltam as seis faces (x0…z1, em mm).")
    if not all(np.isfinite(v)):
        raise Recusa(u"Caixa inválida: há face que não é número.")
    out = {}
    for i, eixo in enumerate("xyz"):
        a, b = sorted((v[2 * i], v[2 * i + 1]))
        lim = float(serie.extensao[i])
        a, b = max(0.0, a), min(lim, b)
        if b - a < CAIXA_MIN_MM:
            raise Recusa(u"A caixa ficou com %.0f mm no eixo %s; o mínimo é "
                         u"%.0f mm, dentro da série." % (max(0.0, b - a), eixo,
                                                          CAIXA_MIN_MM))
        out[eixo + "0"], out[eixo + "1"] = a, b
    return out


def caixa_inicial(serie):
    pv = serie.previa
    c = pv["sp"]
    m = pv["mask"].astype(bool)
    ext = serie.extensao
    if not m.any():
        cx, cz, ypele = ext[0] / 2.0, ext[2] / 2.0, ext[1] / 3.0
    else:
        zz, yy, xx = np.nonzero(m)
        cz = 0.5 * (zz.min() + zz.max()) * c
        cx = 0.5 * (xx.min() + xx.max()) * c
        iz, ix = int(round(cz / c)), int(round(cx / c))
        col = m[min(iz, m.shape[0] - 1), :, min(ix, m.shape[2] - 1)]
        ypele = (float(np.argmax(col)) * c) if col.any() else float(yy.min() * c)
    cx_ = {"x0": cx - 50.0, "x1": cx + 50.0, "y0": ypele - 25.0,
           "y1": ypele + 35.0, "z0": cz - 40.0, "z1": cz + 40.0}
    return normalizar_caixa(serie, cx_)


def parece_face(serie, caixa):
    pv = serie.previa
    if pv is None:
        return False
    c = pv["sp"]
    m = pv["mask"]
    z0 = max(0, int(math.floor(caixa["z0"] / c)))
    z1 = min(m.shape[0] - 1, int(math.ceil(caixa["z1"] / c)))
    if z1 < z0:
        return False
    fatias = m[z0:z1 + 1].astype(bool)
    xs = np.nonzero(fatias.any(axis=(0, 1)))[0]
    if xs.size == 0:
        return False
    largura = (xs.max() - xs.min() + 1) * c
    return bool(largura <= 220.0)



_KUHN = np.array([[0, 1, 3, 7], [0, 1, 5, 7], [0, 2, 3, 7],
                  [0, 2, 6, 7], [0, 4, 5, 7], [0, 4, 6, 7]], dtype=np.int64)
_CANTO = np.array([[c & 1, (c >> 1) & 1, (c >> 2) & 1] for c in range(8)],
                  dtype=np.int64)
_OUTROS = np.array([[1, 2, 3], [0, 2, 3], [0, 1, 3], [0, 1, 2]],
                   dtype=np.int64)
_PAR = {}
for _m in range(16):
    _d = [i for i in range(4) if (_m >> i) & 1]
    if len(_d) == 2:
        _f = [i for i in range(4) if i not in _d]
        _PAR[_m] = (_d[0], _d[1], _f[0], _f[1])


CELULAS_POR_FATIA = 1500000


def _cruzamentos_da_fatia(F, plano, z0, z1):
    Z, Y, X = F.shape
    dentro = F[z0:z1 + 1] < 0
    nz = z1 - z0
    todos = dentro[:-1, :-1, :-1].copy()
    algum = todos.copy()
    for dz in (0, 1):
        for dy in (0, 1):
            for dx in (0, 1):
                s = dentro[dz:nz + dz, dy:Y - 1 + dy, dx:X - 1 + dx]
                todos &= s
                algum |= s
    algum &= ~todos
    del todos, dentro
    cz, cy, cx = np.nonzero(algum)
    del algum
    vazio = np.zeros((0, 3), dtype=np.int64)
    if cz.size == 0:
        return vazio, vazio
    base = ((cz.astype(np.int64) + z0) * Y + cy) * X + cx
    del cz, cy, cx
    desl = (_CANTO[:, 2] * Y + _CANTO[:, 1]) * X + _CANTO[:, 0]
    g = (base[:, None] + desl[None, :])[:, _KUHN].reshape(-1, 4)
    del base
    ins = plano[g] < 0
    n_in = ins.sum(axis=1)
    fica = (n_in > 0) & (n_in < 4)
    g, ins, n_in = g[fica], ins[fica], n_in[fica]

    tri_a, tri_b = [], []
    um = (n_in == 1) | (n_in == 3)
    if um.any():
        gi, ii = g[um], ins[um]
        so = np.where(n_in[um] == 1, np.argmax(ii, axis=1),
                      np.argmax(~ii, axis=1))
        outros = _OUTROS[so]
        a = gi[np.arange(len(gi)), so]
        b = gi[np.arange(len(gi))[:, None], outros]
        tri_a.append(np.repeat(a[:, None], 3, axis=1))
        tri_b.append(b)
    dois = n_in == 2
    if dois.any():
        gi, ii = g[dois], ins[dois]
        mask = (ii * np.array([1, 2, 4, 8])).sum(axis=1)
        tab = np.array([_PAR.get(int(m), (0, 0, 0, 0)) for m in range(16)])
        i0, i1, o0, o1 = [tab[mask, k] for k in range(4)]
        r = np.arange(len(gi))
        e00 = (gi[r, i0], gi[r, o0])
        e01 = (gi[r, i0], gi[r, o1])
        e11 = (gi[r, i1], gi[r, o1])
        e10 = (gi[r, i1], gi[r, o0])
        tri_a.append(np.stack([e00[0], e01[0], e11[0]], axis=1))
        tri_b.append(np.stack([e00[1], e01[1], e11[1]], axis=1))
        tri_a.append(np.stack([e00[0], e11[0], e10[0]], axis=1))
        tri_b.append(np.stack([e00[1], e11[1], e10[1]], axis=1))
    if not tri_a:
        return vazio, vazio
    return np.concatenate(tri_a), np.concatenate(tri_b)


def superficie(F, celulas_por_fatia=None, posicao=None, com_chaves=False):
    F = np.ascontiguousarray(F, dtype=np.float32)
    if F.ndim != 3 or min(F.shape) < 2:
        out = [np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)]
        if posicao is not None:
            out.append(np.zeros(0, dtype=np.int8))
        if com_chaves:
            out.append(np.zeros(0, dtype=np.int64))
        return tuple(out)
    if (F == 0).any():
        F = np.where(F == 0, np.float32(1e-6), F)
    Z, Y, X = F.shape
    plano = F.ravel()
    N = np.int64(F.size)
    passo = max(1, int((celulas_por_fatia or CELULAS_POR_FATIA)
                       // max(1, (Y - 1) * (X - 1))))

    def _xyz(li):
        return np.stack([li % X, (li // X) % Y, li // (X * Y)],
                        axis=1).astype(np.float64)

    chaves, posicoes, faces_f, rotulos = [], [], [], []
    base_v = 0
    for z0 in range(0, Z - 1, passo):
        z1 = min(Z - 1, z0 + passo)
        A, B = _cruzamentos_da_fatia(F, plano, z0, z1)
        if len(A) == 0:
            continue
        lo = np.minimum(A, B).ravel()
        hi = np.maximum(A, B).ravel()
        primeira, inversa = _unicos(lo * N + hi)
        vlo, vhi = lo[primeira], hi[primeira]
        chave = vlo * N + vhi
        del lo, hi
        if posicao is None:
            flo = plano[vlo].astype(np.float64)
            fhi = plano[vhi].astype(np.float64)
            t = flo / (flo - fhi)
            del flo, fhi
        else:
            t, rot = posicao(vlo, vhi)
            t = np.asarray(t, dtype=np.float64)
            rotulos.append(np.asarray(rot, dtype=np.int8))
        plo, phi = _xyz(vlo), _xyz(vhi)
        verts = plo + t[:, None] * (phi - plo)
        del plo, phi, t, vlo, vhi
        faces = inversa.reshape(-1, 3).astype(np.int64)
        del inversa
        a0, b0 = A[:, 0], B[:, 0]
        ref = _xyz(b0) - _xyz(a0)
        ref[plano[a0] >= 0] *= -1.0
        del A, B, a0, b0
        v0 = verts[faces[:, 0]]
        nrm = np.cross(verts[faces[:, 1]] - v0, verts[faces[:, 2]] - v0)
        trocar = (nrm * ref).sum(1) < 0
        del nrm, ref, v0
        faces[trocar] = faces[trocar][:, [0, 2, 1]]
        chaves.append(chave)
        posicoes.append(verts)
        faces_f.append(faces + base_v)
        base_v += len(verts)
    if not chaves:
        out = [np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64)]
        if posicao is not None:
            out.append(np.zeros(0, dtype=np.int8))
        if com_chaves:
            out.append(np.zeros(0, dtype=np.int64))
        return tuple(out)
    chave = np.concatenate(chaves)
    del chaves
    primeira, inversa = _unicos(chave)
    chave_v = chave[primeira] if com_chaves else None
    del chave
    verts = np.concatenate(posicoes)[primeira]
    del posicoes
    faces = np.concatenate(faces_f)
    del faces_f
    out = [verts, inversa[faces]]
    if posicao is not None:
        out.append(np.concatenate(rotulos)[primeira])
    if com_chaves:
        out.append(chave_v)
    return tuple(out)


def _unicos(chave):
    ordem = np.argsort(chave, kind="stable")
    srt = chave[ordem]
    novo = np.empty(srt.size, dtype=bool)
    if srt.size:
        novo[0] = True
        novo[1:] = srt[1:] != srt[:-1]
    grupo = np.cumsum(novo) - 1
    inversa = np.empty(srt.size, dtype=np.int64)
    inversa[ordem] = grupo
    return ordem[novo], inversa


def conferir_malha(verts, faces):
    f = np.asarray(faces, dtype=np.int64)
    v = np.asarray(verts, dtype=np.float64)
    if f.size == 0:
        return {"fechada": False, "triangulos": 0, "arestas_sem_par": 0,
                "arestas_repetidas": 0, "volume_mm3": 0.0}
    T = len(f)
    n = np.int64(max(len(v), 1))
    srt = np.empty(3 * T, dtype=np.int64)
    for j in range(3):
        srt[j * T:(j + 1) * T] = f[:, j] * n + f[:, (j + 1) % 3]
    srt.sort()
    igual = srt[1:] == srt[:-1]
    repetidas = int((igual[1:] & ~igual[:-1]).sum() + bool(igual[:1].any()))
    del igual
    sem_par = 0
    for j in range(3):
        for i0 in range(0, T, BLOCO_TRIANGULOS):
            fa = f[i0:i0 + BLOCO_TRIANGULOS, j]
            fb = f[i0:i0 + BLOCO_TRIANGULOS, (j + 1) % 3]
            oposta = fb * n + fa
            pos = np.clip(np.searchsorted(srt, oposta), 0, srt.size - 1)
            sem_par += int((srt[pos] != oposta).sum())
    del srt
    return {"fechada": bool(repetidas == 0 and sem_par == 0),
            "triangulos": int(T), "arestas_sem_par": sem_par,
            "arestas_repetidas": repetidas,
            "volume_mm3": float(volume_assinado(v, f))}


BLOCO_TRIANGULOS = 200000


def volume_assinado(verts, faces):
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if f.size == 0:
        return 0.0
    soma = 0.0
    for i0 in range(0, len(f), BLOCO_TRIANGULOS):
        fb = f[i0:i0 + BLOCO_TRIANGULOS]
        a, b, c = v[fb[:, 0]], v[fb[:, 1]], v[fb[:, 2]]
        soma += float((a * np.cross(b, c)).sum())
    return soma / 6.0



def stl_binario(verts, faces, cabecalho=None):
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    T = len(f)
    buf = bytearray(84 + 50 * T)
    cab = CABECALHO_STL if cabecalho is None else bytes(cabecalho)
    if cab.lstrip().lower().startswith(b"solid"):
        raise ValueError(u"cabeçalho de STL binário não pode começar com «solid»")
    buf[:80] = cab[:80].ljust(80, b" ")
    buf[80:84] = struct.pack("<I", T)
    rec = np.frombuffer(buf, dtype=_DTYPE_STL, count=T, offset=84)
    for i0 in range(0, T, BLOCO_TRIANGULOS):
        i1 = min(T, i0 + BLOCO_TRIANGULOS)
        tri = v[f[i0:i1]]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        comp = np.linalg.norm(n, axis=1)
        n = np.where(comp[:, None] > 0, n / np.maximum(comp, 1e-30)[:, None],
                     0.0)
        rec["n"][i0:i1] = n
        rec["v"][i0:i1] = tri
    del rec
    return bytes(buf)


def _triangulos_do_stl(dados):
    n = struct.unpack("<I", dados[80:84])[0]
    return np.frombuffer(dados, dtype=_DTYPE_STL, count=n, offset=84)["v"]


def ler_stl(dados):
    if len(dados) < 84:
        raise ValueError(u"STL curto demais")
    cab = bytes(dados[:80])
    n = struct.unpack("<I", dados[80:84])[0]
    if len(dados) != 84 + 50 * n:
        raise ValueError(u"STL com %d bytes para %d triângulos" % (len(dados), n))
    rec = np.frombuffer(dados, dtype=_DTYPE_STL, count=n, offset=84)
    return cab, rec["v"].astype(np.float64), rec["n"].astype(np.float64)


def cabecalho_seguro(cab):
    c = bytes(cab or b"")
    return (len(c) == 80 and not c.lstrip().lower().startswith(b"solid")
            and b"UNAPPROVED" in c)


def nome_do_arquivo(modo, espessura_mm, sorteio):
    m = {"anatomico": "anatomical", "caixa": "box"}.get(str(modo), "bolus")
    s = u"".join(ch for ch in str(sorteio or u"") if ch in u"0123456789abcdef")
    if str(modo) == "caixa":
        if espessura_mm is None:
            return u"RadAI_bolus_DRAFT_box_%s.stl" % s[:8]
        return u"RadAI_bolus_DRAFT_box_measured%dmm_%s.stl" % (
            int(round(float(espessura_mm))), s[:8])
    return u"RadAI_bolus_DRAFT_%s_%dmm_%s.stl" % (m, int(espessura_mm), s[:8])


def espessura_do_nome(res):
    if res.get("modo") == "caixa":
        return (res.get("espessura") or {}).get("mediana")
    return res.get("espessura_mm")


def nome_do_stl(res, sorteio):
    return nome_do_arquivo(res.get("modo"), espessura_do_nome(res), sorteio)


_ABERTURA_NO_NOME = {"externa": "external", "superior": "superior",
                     "inferior": "inferior", "esquerda": "left",
                     "direita": "right"}


def nome_do_molde(res, sorteio):
    m = res.get("molde") or {}
    s = u"".join(ch for ch in str(sorteio or u"")
                 if ch in u"0123456789abcdef")[:8]
    raiz = nome_do_stl(res, sorteio)[:-len(u".stl")]
    if raiz.endswith(u"_" + s):
        raiz = raiz[:-(len(s) + 1)]
    return u"%s_MOLD_wall%dmm_open-%s_%s.stl" % (
        raiz, int(m.get("casca_mm") or 0),
        _ABERTURA_NO_NOME.get(m.get("abertura"), u"unknown"), s)


def linha_do_ato(res, nome):
    e = res.get("espessura")
    medida = (u"%.1f/%.1f/%.1f mm" % (e["min"], e["mediana"], e["max"])
              if e else u"-")
    if res.get("modo") == "caixa":
        pedida = u"sem camada pedida (bloco da caixa até a pele)"
    else:
        pedida = u"camada pedida %d mm" % int(res.get("espessura_mm") or 0)
    return (u"[bolus] STL exportado por ato declarado: %s | modo %s | %s | "
            u"suavizacao %.1f mm | %d triangulos | espessura medida "
            u"min/mediana/max %s" % (nome, res.get("modo"), pedida,
                                     float(res.get("suavizacao_mm") or 0.0),
                                     int(res["malha"]["triangulos"]), medida))


def linha_do_ato_molde(res, nome):
    m = res.get("molde") or {}
    e = m.get("espessura")
    medida = (u"%.2f/%.2f/%.2f mm" % (e["min"], e["mediana"], e["max"])
              if e else u"-")
    return (u"[bolus] STL do MOLDE exportado por ato declarado: %s | casca "
            u"pedida %d mm | casca medida min/mediana/max %s | abertura %s "
            u"(%.1f cm2) | %d triangulos | do bolus: modo %s" % (
                nome, int(m.get("casca_mm") or 0), medida,
                m.get("abertura"), float(m.get("abertura_mm2") or 0.0) / 100.0,
                int((m.get("malha") or {}).get("triangulos") or 0),
                res.get("modo")))


def conferir_ato(declaro, frase):
    if declaro is not True:
        raise Recusa(u"Exportação recusada: falta o ato declarado. Marque a "
                     u"declaração — ela vale para uma exportação só.")
    if u" ".join(str(frase or u"").split()) != u" ".join(FRASE_DO_ATO.split()):
        raise Recusa(u"Exportação recusada: a frase declarada não é a do ato.")
    return True



def _cruzamentos_z(t, X, Y):
    x = t[:, :, 0] - 1.37e-4
    y = t[:, :, 1] - 2.71e-4
    z = t[:, :, 2]
    xmn = np.clip(np.ceil(x.min(1)), 0, X - 1).astype(np.int64)
    xmx = np.clip(np.floor(x.max(1)), -1, X - 1).astype(np.int64)
    ymn = np.clip(np.ceil(y.min(1)), 0, Y - 1).astype(np.int64)
    ymx = np.clip(np.floor(y.max(1)), -1, Y - 1).astype(np.int64)
    nx = np.maximum(0, xmx - xmn + 1)
    ny = np.maximum(0, ymx - ymn + 1)
    cont = nx * ny
    if cont.sum() == 0:
        return np.zeros(0, np.int64), np.zeros(0)
    rep = np.repeat(np.arange(len(t)), cont)
    ini = np.repeat(np.cumsum(cont) - cont, cont)
    k = np.arange(cont.sum()) - ini
    ix = xmn[rep] + k % nx[rep]
    iy = ymn[rep] + k // nx[rep]
    x0, x1, x2 = x[rep, 0], x[rep, 1], x[rep, 2]
    y0, y1, y2 = y[rep, 0], y[rep, 1], y[rep, 2]
    d = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
    ok = np.abs(d) > 1e-12
    dd = np.where(ok, d, 1.0)
    l0 = ((y1 - y2) * (ix - x2) + (x2 - x1) * (iy - y2)) / dd
    l1 = ((y2 - y0) * (ix - x2) + (x0 - x2) * (iy - y2)) / dd
    l2 = 1.0 - l0 - l1
    dentro = ok & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
    zc = l0 * z[rep, 0] + l1 * z[rep, 1] + l2 * z[rep, 2]
    return (iy * X + ix)[dentro], zc[dentro]


def voxelizar(tri, forma, para_indice=None):
    Z, Y, X = [int(v) for v in forma]
    vazio = np.zeros((Z, Y, X), dtype=bool)
    T = len(tri)
    if T == 0:
        return vazio, 0
    cols, zs = [], []
    for i0 in range(0, T, BLOCO_TRIANGULOS):
        t = np.asarray(tri[i0:i0 + BLOCO_TRIANGULOS], dtype=np.float64)
        if para_indice is not None:
            t = para_indice(t)
        c, z = _cruzamentos_z(t, X, Y)
        cols.append(c)
        zs.append(z)
    del t
    col, zc = np.concatenate(cols), np.concatenate(zs)
    del cols, zs
    if col.size == 0:
        return vazio, 0
    ordem = np.lexsort((zc, col))
    col, zc = col[ordem], zc[ordem]
    ucol, ini_col, n_col = np.unique(col, return_index=True,
                                     return_counts=True)
    impar = n_col % 2 == 1
    rank = np.arange(col.size) - np.repeat(ini_col, n_col)
    boa = ~np.repeat(impar, n_col)
    entra = boa & (rank % 2 == 0)
    j = np.nonzero(entra)[0]
    za, zb, cc = zc[j], zc[j + 1], col[j]
    a = np.clip(np.ceil(za), 0, Z).astype(np.int64)
    b = np.clip(np.floor(zb) + 1, 0, Z).astype(np.int64)
    val = b > a
    del vazio
    dif = np.zeros((Z + 1, Y * X), dtype=np.int8)
    np.add.at(dif, (a[val], cc[val]), 1)
    np.add.at(dif, (b[val], cc[val]), -1)
    np.cumsum(dif, axis=0, dtype=np.int8, out=dif)
    cheio = dif[:Z] > 0
    del dif
    return cheio.reshape(Z, Y, X), int(impar.sum())


def dentro_da_malha(tri, pontos):
    t = np.asarray(tri, dtype=np.float64)
    out = []
    for p in np.asarray(pontos, dtype=np.float64).reshape(-1, 3):
        px, py = p[0] + 1.37e-4, p[1] + 2.71e-4
        x, y, z = t[:, :, 0], t[:, :, 1], t[:, :, 2]
        d = (y[:, 1] - y[:, 2]) * (x[:, 0] - x[:, 2]) + \
            (x[:, 2] - x[:, 1]) * (y[:, 0] - y[:, 2])
        ok = np.abs(d) > 1e-12
        dd = np.where(ok, d, 1.0)
        l0 = ((y[:, 1] - y[:, 2]) * (px - x[:, 2]) +
              (x[:, 2] - x[:, 1]) * (py - y[:, 2])) / dd
        l1 = ((y[:, 2] - y[:, 0]) * (px - x[:, 2]) +
              (x[:, 0] - x[:, 2]) * (py - y[:, 2])) / dd
        l2 = 1 - l0 - l1
        acerta = ok & (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        zc = l0 * z[:, 0] + l1 * z[:, 1] + l2 * z[:, 2]
        out.append(bool(((zc > p[2]) & acerta).sum() % 2 == 1))
    return np.array(out, dtype=bool)


def dsc(a, b):
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    s = int(a.sum()) + int(b.sum())
    return 1.0 if s == 0 else 2.0 * int((a & b).sum()) / float(s)



_GLIFOS = {
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "^": ("..#..", ".###.", "#.#.#", "..#..", "..#..", "..#..", "..#.."),
}


def _bitmap(texto):
    linhas = [u""] * 7
    for i, ch in enumerate(texto):
        g = _GLIFOS[ch]
        for r in range(7):
            linhas[r] += (u".." if i else u"") + g[r]
    return np.array([[c == u"#" for c in l] for l in linhas], dtype=bool)


def _eixos_da_colocacao(direcao):
    an, sn = _NORMAL[direcao]
    au, su = _CIMA[direcao]
    n = np.zeros(3)
    n[an] = sn
    u = np.zeros(3)
    u[au] = su
    r = np.cross(-n, u)
    ar = int(np.argmax(np.abs(r)))
    return (an, sn), (au, su), (ar, int(np.sign(r[ar])))


def _vista(arr, direcao):
    (an, sn), (au, su), (ar, sr) = _eixos_da_colocacao(direcao)
    ax = {0: 2, 1: 1, 2: 0}
    v = np.transpose(arr, (ax[an], ax[au], ax[ar]))
    if sn < 0:
        v = v[::-1]
    if su < 0:
        v = v[:, ::-1]
    if sr < 0:
        v = v[:, :, ::-1]
    return v


def _marcas(F, h, direcao, letra_por_posicao):
    relato = {"colocadas": False, "letra": u"", "seta": u"", "entalhe": False,
              "motivo": u""}
    zona = np.zeros(F.shape, dtype=bool)
    V = _vista(F, direcao)
    Zv = _vista(zona, direcao)
    M = V < 0
    P = M.any(axis=0)
    if not P.any():
        relato["motivo"] = u"sem bólus"
        return F, relato, zona
    us, rs = np.nonzero(P)
    s = (rs - rs.min()) + (us.max() - us)
    L_mm = float(np.clip(0.15 * min(np.ptp(us) + 1, np.ptp(rs) + 1) * h,
                         4.0, 15.0))
    L = L_mm / h
    s0 = float(s.min())
    kk_u, kk_r = np.meshgrid(np.arange(P.shape[0]), np.arange(P.shape[1]),
                             indexing="ij")
    ss = (kk_r - rs.min()) + (us.max() - kk_u)
    campo = (s0 + L - ss) * h / math.sqrt(2.0)
    np.maximum(V, campo[None, :, :].astype(V.dtype), out=V)
    Zv[...] |= (campo > -3.0 * h)[None, :, :]
    relato["entalhe"] = bool((campo > 0)[P].any())
    M = V < 0
    P = M.any(axis=0)
    cel = max(1, int(round(CELULA_MM / h)))
    alto = max(1, int(math.ceil(RELEVO_MM / h)))
    bm = _bitmap(u"R^")
    Hb, Wb = bm.shape[0] * cel, bm.shape[1] * cel
    folga = cel
    Ht, Wt = Hb + 2 * folga, Wb + 2 * folga
    livre = P & ~(campo > -2.0 * cel * h)
    if livre.shape[0] < Ht or livre.shape[1] < Wt:
        relato["motivo"] = u"a pegada do bólus é menor que o bloco da marca"
        return F, relato, zona
    si = np.pad(np.cumsum(np.cumsum(livre.astype(np.int64), 0), 1),
                ((1, 0), (1, 0)))
    soma = (si[Ht:, Wt:] - si[:-Ht, Wt:] - si[Ht:, :-Wt] + si[:-Ht, :-Wt])
    cabe = soma == Ht * Wt
    if not cabe.any():
        relato["motivo"] = u"não há área lisa inteira para o bloco da marca"
        return F, relato, zona
    cu, cr = np.nonzero(cabe)
    mu, mr = us.mean(), rs.mean()
    d2 = (cu + Ht / 2.0 - mu) ** 2 + (cr + Wt / 2.0 - mr) ** 2
    k = int(np.argmax(d2))
    u0, r0 = int(cu[k]) + folga, int(cr[k]) + folga
    letra = letra_por_posicao(u0 + Hb / 2.0, r0 + Wb / 2.0)
    bm = _bitmap(letra + u"^")
    rev = M[::-1]
    tem = rev.any(axis=0)
    topo = (M.shape[0] - 1 - np.argmax(rev, axis=0))
    for i in range(bm.shape[0]):
        for j in range(bm.shape[1]):
            if not bm[i, j]:
                continue
            ku0 = u0 + (bm.shape[0] - 1 - i) * cel
            kr0 = r0 + j * cel
            for du in range(cel):
                for dr in range(cel):
                    ku, kr = ku0 + du, kr0 + dr
                    if not tem[ku, kr]:
                        continue
                    t0 = int(topo[ku, kr])
                    t1 = min(V.shape[0] - 2, t0 + alto)
                    V[t0:t1 + 1, ku, kr] = np.minimum(V[t0:t1 + 1, ku, kr],
                                                      -0.5)
    Zv[:, max(0, u0 - cel):u0 + Hb + cel, max(0, r0 - cel):r0 + Wb + cel] = True
    relato.update({"colocadas": True, "letra": letra, "seta": u"^",
                   "motivo": u""})
    return F, relato, zona



def _sdf_caixa(forma_zyx, lo, hi):
    Z, Y, X = forma_zyx
    c = (np.asarray(lo, dtype=np.float64) + np.asarray(hi)) / 2.0
    m = (np.asarray(hi, dtype=np.float64) - np.asarray(lo)) / 2.0
    qx = (np.abs(np.arange(X) - c[0]) - m[0]).astype(np.float32)[None, None, :]
    qy = (np.abs(np.arange(Y) - c[1]) - m[1]).astype(np.float32)[None, :, None]
    qz = (np.abs(np.arange(Z) - c[2]) - m[2]).astype(np.float32)[:, None, None]
    zero = np.float32(0.0)
    fora = np.empty((Z, Y, X), dtype=np.float32)
    fora[...] = np.maximum(qx, zero) ** 2
    fora += np.maximum(qy, zero) ** 2
    fora += np.maximum(qz, zero) ** 2
    np.sqrt(fora, out=fora)
    dentro = np.empty((Z, Y, X), dtype=np.float32)
    np.maximum(np.maximum(qx, qy), qz, out=dentro)
    np.minimum(dentro, zero, out=dentro)
    fora += dentro
    return fora


def direcao_automatica(solido, lo, hi):
    lo = [int(round(v)) for v in lo]
    hi = [int(round(v)) for v in hi]
    sub = solido[lo[2]:hi[2] + 1, lo[1]:hi[1] + 1, lo[0]:hi[0] + 1]
    if sub.size == 0:
        return "ant"
    fr = {}
    for d, (eixo, sinal) in _NORMAL.items():
        ax = {0: 2, 1: 1, 2: 0}[eixo]
        k = sub.shape[ax] - 1 if sinal > 0 else 0
        face = np.take(sub, k, axis=ax)
        fr[d] = float(face.mean()) if face.size else 0.0
    opos = {"ant": "post", "post": "ant", "dir": "esq", "esq": "dir",
            "sup": "inf", "inf": "sup"}
    return max(DIRECOES, key=lambda d: (fr[opos[d]] - fr[d],
                                        -DIRECOES.index(d)))


def _acessivel(solido, direcao):
    eixo, sinal = _NORMAL[direcao]
    ax = {0: 2, 1: 1, 2: 0}[eixo]
    s = solido if sinal < 0 else np.flip(solido, axis=ax)
    bloq = np.logical_or.accumulate(s, axis=ax)
    if sinal > 0:
        bloq = np.flip(bloq, axis=ax)
    return ~bloq


def _grade(serie, caixa, margem_extra, casca_mm=None):
    tam = np.array([caixa["x1"] - caixa["x0"], caixa["y1"] - caixa["y0"],
                    caixa["z1"] - caixa["z0"]], dtype=np.float64)
    grades = GRADES_MM
    if casca_mm is not None:
        grades = tuple(h for h in GRADES_MM
                       if float(casca_mm) > _CASCA_POR_GRADE * h + 1e-9)
    for h in grades:
        m = margem_extra + 3.0 * h
        n = np.ceil((tam + 2 * m) / h).astype(int) + 1
        if int(np.prod(n)) <= TETO_POR_GRADE.get(h, TETO_VOXELS):
            off = np.array([caixa["x0"], caixa["y0"], caixa["z0"]]) - m
            return h, off, (int(n[2]), int(n[1]), int(n[0]))
    if casca_mm is not None and grades != GRADES_MM:
        h = grades[-1] if grades else GRADES_MM[0]
        m = margem_extra + 3.0 * h
        n = np.ceil((tam + 2 * m) / h).astype(int) + 1
        raise Recusa(u"Casca de %d mm: a parede do molde só sai inteira numa "
                     u"grade de no máximo %.2f mm, e esta caixa não cabe nela "
                     u"(%.1f milhões de voxels a %.2f mm; o teto dessa grade "
                     u"é %.1f milhões). Diminua a caixa ou use casca de %d mm "
                     u"ou mais."
                     % (int(casca_mm), float(casca_mm) / _CASCA_POR_GRADE,
                        np.prod(n) / 1e6, h,
                        TETO_POR_GRADE.get(h, TETO_VOXELS) / 1e6,
                        int(math.floor(_CASCA_POR_GRADE * GRADES_MM[-1])) + 1))
    h = GRADES_MM[-1]
    m = margem_extra + 3.0 * h
    n = np.ceil((tam + 2 * m) / h).astype(int) + 1
    raise Recusa(u"Caixa grande demais: %.1f milhões de voxels a %.1f mm, e o "
                 u"teto é %.0f milhões. Diminua a caixa — o teto existe para "
                 u"o bólus não disputar memória com o contorno da noite."
                 % (np.prod(n) / 1e6, h, TETO_VOXELS / 1e6))


def _trilinear(arr, pts_xyz, output=None):
    from scipy import ndimage
    p = np.asarray(pts_xyz, dtype=np.float64)
    return ndimage.map_coordinates(arr, [p[:, 2], p[:, 1], p[:, 0]], order=1,
                                   mode="nearest", output=output)


def _distancia_fora(solido, passo_mm=1.0):
    import SimpleITK as sitk
    im = sitk.GetImageFromArray(np.ascontiguousarray(solido).view(np.uint8))
    im.SetSpacing((float(passo_mm),) * 3)
    d_img = sitk.SignedMaurerDistanceMap(im, insideIsPositive=False,
                                         squaredDistance=False,
                                         useImageSpacing=True)
    del im
    d = sitk.GetArrayFromImage(d_img)
    del d_img
    np.maximum(d, np.float32(0.0), out=d)
    return d


def _ponto_triangulo(p, a, b, c):
    ab, ac, ap = b - a, c - a, p - a
    bp, cp = p - b, p - c
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        den = va + vb + vc
        den = np.where(np.abs(den) < 1e-18, 1e-18, den)
        q = a + ab * (vb / den)[:, None] + ac * (vc / den)[:, None]
        e1, e2 = d4 - d3, d5 - d6
        t = np.where(np.abs(e1 + e2) < 1e-18, 0.0, e1 / (e1 + e2))
        q = np.where(((va <= 0) & (e1 >= 0) & (e2 >= 0))[:, None],
                     b + (c - b) * t[:, None], q)
        t = np.where(np.abs(d2 - d6) < 1e-18, 0.0, d2 / (d2 - d6))
        q = np.where(((vb <= 0) & (d2 >= 0) & (d6 <= 0))[:, None],
                     a + ac * t[:, None], q)
        q = np.where(((d6 >= 0) & (d5 <= d6))[:, None], c, q)
        t = np.where(np.abs(d1 - d3) < 1e-18, 0.0, d1 / (d1 - d3))
        q = np.where(((vc <= 0) & (d1 >= 0) & (d3 <= 0))[:, None],
                     a + ab * t[:, None], q)
        q = np.where(((d3 >= 0) & (d4 <= d3))[:, None], b, q)
        q = np.where(((d1 <= 0) & (d2 <= 0))[:, None], a, q)
    return np.linalg.norm(p - q, axis=1)


MEDIDAS_FINOS, MEDIDAS_GROSSOS, MEDIDAS_UNIFORMES = 1000, 500, 1500


def medir_espessura(verts, faces, J, E, zona, eixo_n, face_n, lateral, h):
    from scipy.spatial import cKDTree
    if len(verts) == 0:
        return None
    jv = _trilinear(J, verts)
    ev = _trilinear(E, verts)
    na_zona = _trilinear(np.ascontiguousarray(zona).view(np.uint8), verts,
                         output=np.float32) > 0.01
    interno = (jv >= ev) & ~na_zona
    externo = (ev > jv) & ~na_zona & lateral(verts)
    if face_n is not None:
        externo &= np.abs(verts[:, eixo_n] - face_n) <= 1.5
    ftri = interno[faces].all(axis=1)
    if not ftri.any() or not externo.any():
        return None
    fi = faces[ftri]
    centro = (verts[fi[:, 0]] + verts[fi[:, 1]] + verts[fi[:, 2]]) / 3.0
    ext = np.nonzero(externo)[0]
    teto = MEDIDAS_FINOS + MEDIDAS_GROSSOS + MEDIDAS_UNIFORMES
    if ext.size > teto:
        lo = np.maximum(np.floor(verts.min(0)).astype(int) - 2, 0)
        hi = np.minimum(np.ceil(verts.max(0)).astype(int) + 3,
                        np.array(J.shape[::-1]))
        sub = J[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]] >= 0
        d_obst = _distancia_fora(sub, 1.0)
        del sub
        est = _trilinear(d_obst, verts[ext] - lo[None, :])
        del d_obst
        finos = ext[np.argpartition(est, MEDIDAS_FINOS)[:MEDIDAS_FINOS]]
        grossos = ext[np.argpartition(-est, MEDIDAS_GROSSOS)[:MEDIDAS_GROSSOS]]
        uniforme = ext[np.linspace(0, ext.size - 1,
                                   MEDIDAS_UNIFORMES).astype(int)]
        alvo = np.unique(np.concatenate([finos, grossos, uniforme]))
    else:
        uniforme = alvo = ext
    k = int(min(8, len(fi)))
    _d, cand = cKDTree(centro, leafsize=32).query(verts[alvo], k=k)
    del centro
    cand = np.asarray(cand).reshape(len(alvo), k)
    pts = np.repeat(verts[alvo], k, axis=0)
    tri = verts[fi[cand.ravel()]]
    d = _ponto_triangulo(pts, tri[:, 0], tri[:, 1], tri[:, 2])
    d_alvo = d.reshape(len(alvo), k).min(axis=1) * h
    posicao = {int(i): j for j, i in enumerate(alvo)}
    d_unif = d_alvo[[posicao[int(i)] for i in uniforme]]
    return {"min": float(d_alvo.min()), "mediana": float(np.median(d_unif)),
            "max": float(d_alvo.max()), "n": int(ext.size),
            "n_medidos": int(alvo.size)}



def _distancia_exata(pontos, tri, arvore, k=None, bloco=None):
    p = np.asarray(pontos, dtype=np.float64).reshape(-1, 3)
    out = np.empty(len(p), dtype=np.float64)
    if len(p) == 0:
        return out
    k = int(max(1, min(k or VIZINHOS_DA_DISTANCIA, len(tri))))
    passo = int(bloco or BLOCO_DISTANCIA)
    for i0 in range(0, len(p), passo):
        q = p[i0:i0 + passo]
        _d, cand = arvore.query(q, k=k)
        cand = np.asarray(cand).reshape(len(q), k)
        t = tri[cand.ravel()]
        d = _ponto_triangulo(np.repeat(q, k, axis=0), t[:, 0], t[:, 1],
                             t[:, 2])
        out[i0:i0 + len(q)] = d.reshape(len(q), k).min(axis=1)
    return out


def _molde(Fp, verts_b, faces_b, h, casca_mm, abertura, direcao):
    from scipy import ndimage
    from scipy.spatial import cKDTree
    t0 = time.time()
    Zp, Yp, Xp = Fp.shape
    t_idx = float(casca_mm) / h
    r_rente = np.float32(RENTE_POR_GRADE * h)
    bol = Fp < 0
    dv = _distancia_fora(bol, 1.0)
    faixa = dv <= np.float32(t_idx + 2.0 * _CASCA_POR_GRADE)
    del dv
    faixa &= ~bol
    faixa[0, :, :] = faixa[-1, :, :] = False
    faixa[:, 0, :] = faixa[:, -1, :] = False
    faixa[:, :, 0] = faixa[:, :, -1] = False
    idx = np.flatnonzero(faixa)
    del faixa
    tri = np.asarray(verts_b, dtype=np.float32)[
        np.asarray(faces_b, dtype=np.int64)]
    arvore = cKDTree(tri.mean(axis=1), leafsize=32)
    P = np.full(Fp.shape, np.float32(1e3), dtype=np.float32)
    P[bol] = np.float32(-float(casca_mm))
    Pr_ = P.ravel()
    for i0 in range(0, idx.size, FAIXA_POR_BLOCO):
        ib = idx[i0:i0 + FAIXA_POR_BLOCO]
        pts = np.stack([ib % Xp, (ib // Xp) % Yp, ib // (Xp * Yp)],
                       axis=1).astype(np.float64) - 1.0
        Pr_[ib] = ((_distancia_exata(pts, tri, arvore) - t_idx) * h
                   ).astype(np.float32)
        del pts
    del idx, Pr_
    if abertura == "externa":
        eixo, sinal = _NORMAL[direcao]
    else:
        eixo, sinal = _ABERTURA_EIXO[abertura]
    ax = {0: 2, 1: 1, 2: 0}[eixo]
    T = None
    if abertura == "externa":
        if sinal > 0:
            M = np.minimum.accumulate(Fp, axis=ax)
        else:
            M = np.flip(np.minimum.accumulate(np.flip(Fp, axis=ax), axis=ax),
                        axis=ax)
        T = np.negative(M, out=M)
        T[np.abs(T) < r_rente] = r_rente
        c_idx = None
    else:
        col = verts_b[:, eixo]
        c_idx = float(col.max() if sinal > 0 else col.min())
        n_ax = Fp.shape[ax]
        coord = (np.arange(n_ax, dtype=np.float64) - 1.0 - c_idx) * sinal * h
        coord[np.abs(coord) < float(r_rente)] = float(r_rente)
        forma = [1, 1, 1]
        forma[ax] = n_ax
        T_1d = coord.astype(np.float32).reshape(forma)
    np.maximum(P, r_rente, out=P, where=np.abs(P) < r_rente)
    G = np.negative(Fp)
    np.maximum(G, P, out=G)
    if T is not None:
        np.maximum(G, T, out=G)
    else:
        np.maximum(G, T_1d, out=G)
    G[0, :, :] = G[-1, :, :] = G[:, 0, :] = G[:, -1, :] = 1.0
    G[:, :, 0] = G[:, :, -1] = 1.0
    rotulo, n_comp = ndimage.label(G < 0, structure=np.ones((3, 3, 3)))
    removido, pecas = 0, int(n_comp)
    if n_comp > 1:
        tam = np.bincount(rotulo.ravel())
        tam[0] = 0
        maior = int(tam.max())
        fora = np.nonzero((tam > 0) & (tam < FRAGMENTO_MAX_FRACAO * maior))[0]
        if fora.size:
            tirar = np.isin(rotulo, fora)
            removido = int(tirar.sum())
            G[tirar] = np.float32(1.0)
            del tirar
            pecas = int(n_comp - fora.size)
    del rotulo

    Fr, Pr, Gr = Fp.ravel(), P.ravel(), G.ravel()
    Tr = T.ravel() if T is not None else None
    passo_ax = (1, Xp, Xp * Yp)[eixo]
    n_ax_ = Fp.shape[ax]

    def _corte(v):
        if Tr is not None:
            return Tr[v].astype(np.float64)
        i = (v // passo_ax) % n_ax_
        return T_1d.ravel()[i].astype(np.float64)

    def posicao(vlo, vhi):
        solido_lo = Gr[vlo] < 0
        flo = Fr[vlo].astype(np.float64)
        fhi = Fr[vhi].astype(np.float64)
        bolo = np.where(solido_lo, fhi < 0, flo < 0)
        a0, b0 = -flo, -fhi
        with np.errstate(divide="ignore", invalid="ignore"):
            t_cav = a0 / (a0 - b0)
        melhor = np.where(solido_lo, np.inf, -np.inf)
        rot = np.full(len(vlo), -1, dtype=np.int8)
        for k, (a, b) in ((1, (Pr[vlo].astype(np.float64),
                               Pr[vhi].astype(np.float64))),
                          (2, (_corte(vlo), _corte(vhi)))):
            valido = np.where(solido_lo, (a < 0) & (b > 0), (b < 0) & (a > 0))
            with np.errstate(divide="ignore", invalid="ignore"):
                t = a / (a - b)
            troca = valido & np.where(solido_lo, t < melhor, t > melhor)
            melhor = np.where(troca, t, melhor)
            rot[troca] = k
        melhor = np.where(bolo, t_cav, melhor)
        rot[bolo] = 0
        return melhor, rot

    verts, faces, rotulos, chaves = superficie(G, posicao=posicao,
                                               com_chaves=True)
    verts -= 1.0
    mask = G[1:-1, 1:-1, 1:-1] < 0
    return {"verts": verts, "faces": faces, "rotulos": rotulos, "G": G,
            "chaves": chaves, "mask": mask, "pecas": pecas, "eixo": int(eixo),
            "fragmentos_mm3": float(removido * h ** 3),
            "sinal": int(sinal), "plano_idx": c_idx, "arvore": arvore,
            "tri_bolus": tri, "tempo_campo_s": round(time.time() - t0, 2)}


def _medir_molde(mo, verts_b, faces_b, chaves_b, h, casca_mm):
    v, rot, km = mo["verts"], mo["rotulos"], mo["chaves"]
    vb = np.asarray(verts_b, dtype=np.float64)
    fb = np.asarray(faces_b, dtype=np.int64)
    ext = np.nonzero(rot == 1)[0]
    esp = None
    if ext.size:
        if ext.size > MEDIDAS_DA_CASCA:
            ext = ext[np.linspace(0, ext.size - 1,
                                  MEDIDAS_DA_CASCA).astype(np.int64)]
        d = _distancia_exata(v[ext], mo["tri_bolus"], mo["arvore"]) * h
        esp = {"min": float(d.min()), "mediana": float(np.median(d)),
               "max": float(d.max()), "n": int((rot == 1).sum()),
               "n_medidos": int(ext.size),
               "p01": float(np.percentile(d, 1)),
               "p99": float(np.percentile(d, 99))}
    internos = np.nonzero(rot == 0)[0]
    kb = np.asarray(chaves_b, dtype=np.int64)
    ordem = np.argsort(kb, kind="stable")
    kb_s = kb[ordem]
    ki = km[internos]
    pos = np.clip(np.searchsorted(kb_s, ki), 0, max(0, kb_s.size - 1))
    achou = (kb_s.size > 0) & (kb_s[pos] == ki)
    jb = ordem[pos]
    iguais = int((achou & (v[internos] == vb[jb]).all(axis=1)).sum())
    presente = np.zeros(len(vb), dtype=bool)
    presente[jb[achou]] = True
    no_molde = presente[fb].all(axis=1)
    del presente, ordem, kb_s, pos, jb
    tb = vb[fb[~no_molde]]
    cr = np.cross(tb[:, 1] - tb[:, 0], tb[:, 2] - tb[:, 0]) * (h * h)
    area = 0.5 * float(np.linalg.norm(cr, axis=1).sum())
    soma = cr.sum(axis=0)
    nrm = soma / max(float(np.linalg.norm(soma)), 1e-30)
    lado = np.zeros(3)
    lado[mo["eixo"]] = mo["sinal"]
    return {"espessura": esp,
            "interior": {"triangulos_do_bolus": int(len(faces_b)),
                         "no_molde": int(no_molde.sum()),
                         "vertices_internos": int(internos.size),
                         "vertices_iguais": iguais},
            "abertura_mm2": area,
            "abertura_normal_quadro": [float(x) for x in nrm],
            "abertura_alinhamento": float(np.dot(nrm, lado))}


ABERTURA_MIN_MM2 = 25.0
CASCA_DESVIO_AVISO_MM = 0.5


def _montar_molde(serie, Fp, verts, faces, chaves, off, h, casca_mm,
                  abertura, direcao, para_indice, modo, marcas):
    t0 = time.time()
    mo = _molde(Fp, verts, faces, h, casca_mm, abertura, direcao)
    med = _medir_molde(mo, verts, faces, chaves, h, casca_mm)
    del mo["arvore"], mo["tri_bolus"], mo["chaves"]
    previa = _previa_do_bolus(mo["mask"], off, h, mo["G"][1:-1, 1:-1, 1:-1])
    del mo["G"]
    vm, fm = mo["verts"], mo["faces"]
    lps = serie.quadro_para_lps(off[None, :] + vm * h)
    faces_lps = fm[:, [0, 2, 1]] if np.linalg.det(serie.D) < 0 else fm
    malha = conferir_malha(lps, faces_lps)
    stl = stl_binario(lps, faces_lps, cabecalho=CABECALHO_STL_MOLDE)
    del lps, faces_lps
    volta, impares = voxelizar(_triangulos_do_stl(stl), mo["mask"].shape,
                               para_indice=para_indice)
    dsc_volta = dsc(volta, mo["mask"])
    del volta
    ext_q = off[None, :] + vm * h
    dims = (ext_q.max(0) - ext_q.min(0)) if len(vm) else np.zeros(3)
    del ext_q
    n_lps = serie.D.dot(np.array(med["abertura_normal_quadro"]))
    avisos = []
    area = med["abertura_mm2"]
    if area < ABERTURA_MIN_MM2:
        avisos.append(u"A abertura %s quase não achou face do bólus "
                      u"(%.0f mm²): desse lado ele não encosta na caixa, e o "
                      u"molde sairia fechado. Escolha outra abertura — o "
                      u"molde não é exportado assim." % (abertura, area))
    e = med["espessura"]
    if e and (e["p01"] < casca_mm - CASCA_DESVIO_AVISO_MM
              or e["p99"] > casca_mm + CASCA_DESVIO_AVISO_MM):
        avisos.append(u"A casca medida na malha vai de %.1f a %.1f mm em 98%% "
                      u"da face externa (pedida: %d mm). Confira antes de "
                      u"imprimir." % (e["p01"], e["p99"], casca_mm))
    if mo["fragmentos_mm3"] > 0:
        avisos.append(u"O corte da abertura soltou fragmentos da casca "
                      u"(%.0f mm³), que foram tirados: impressos, eles cairiam."
                      % mo["fragmentos_mm3"])
    if mo["pecas"] > 1:
        avisos.append(u"O molde saiu em %d peças: o bólus desta caixa tem "
                      u"partes separadas." % mo["pecas"])
    if abertura == "externa" and modo == "anatomico":
        avisos.append(u"Abertura externa: a face externa do bólus segue a "
                      u"pele, e a cera assenta plana — ela não reproduz essa "
                      u"face. Para o bólus sair inteiro, abra por uma lateral.")
    if abertura == "externa" and (marcas or {}).get("colocadas"):
        avisos.append(u"As marcas de lado ficam na face aberta: a cera não as "
                      u"reproduz.")
    interior_ok = (med["interior"]["vertices_iguais"]
                   == med["interior"]["vertices_internos"])
    exportavel = bool(malha["fechada"] and area >= ABERTURA_MIN_MM2
                      and interior_ok)
    return {
        "casca_mm": int(casca_mm), "abertura": abertura,
        "malha": malha, "dsc_ida_volta": float(dsc_volta),
        "colunas_impares": int(impares), "pecas": int(mo["pecas"]),
        "fragmentos_mm3": mo["fragmentos_mm3"],
        "espessura": e, "interior": med["interior"],
        "abertura_mm2": float(area),
        "abertura_normal_lps": [float(x) for x in n_lps],
        "abertura_alinhamento": med["abertura_alinhamento"],
        "volume_cm3": malha["volume_mm3"] / 1000.0,
        "dimensoes_mm": [float(v) for v in dims], "avisos": avisos,
        "exportavel": exportavel, "tempo_s": round(time.time() - t0, 2),
        "stl": stl, "mask": mo["mask"], "previa": previa,
    }


def campos_da_pele(serie, cx, h, off, forma, direcao):
    import SimpleITK as sitk
    from scipy import ndimage
    avisos = []
    Z, Y, X = forma
    origem_w = serie.quadro_para_lps(off)[0]
    hu = sitk.GetArrayFromImage(sitk.Resample(
        serie.img, (X, Y, Z), sitk.Transform(), sitk.sitkLinear,
        tuple(origem_w), (h, h, h), serie.img.GetDirection(), -1000.0,
        sitk.sitkFloat32))
    solido = hu > LIMIAR_HU

    pv = serie.previa
    corpo = solido
    if pv is not None and pv.get("sem_mesa"):
        c = pv["sp"]
        zz = (off[2] + np.arange(Z) * h) / c
        yy = (off[1] + np.arange(Y) * h) / c
        xx = (off[0] + np.arange(X) * h) / c
        g = pv["mask"]
        iz = np.clip(np.round(zz).astype(int), 0, g.shape[0] - 1)
        iy = np.clip(np.round(yy).astype(int), 0, g.shape[1] - 1)
        ix = np.clip(np.round(xx).astype(int), 0, g.shape[2] - 1)
        perto = ndimage.binary_dilation(g > 0, iterations=2)
        corpo = perto[np.ix_(iz, iy, ix)]
        del perto
        corpo &= solido
        if not corpo.any():
            corpo = solido
    else:
        avisos.append(u"Contorno externo sem remoção de mesa: a mesa pode "
                      u"contar como corpo perto da caixa.")

    lo = (np.array([cx["x0"], cx["y0"], cx["z0"]]) - off) / h
    hi = (np.array([cx["x1"], cx["y1"], cx["z1"]]) - off) / h
    if direcao in (None, "", "auto"):
        direcao = direcao_automatica(solido, lo, hi)
        dir_auto = True
    elif direcao in DIRECOES:
        dir_auto = False
    else:
        raise Recusa(u"Direção de colocação desconhecida: %s." % direcao)

    bloqueado = _acessivel(solido, direcao)
    bloqueado |= solido
    np.logical_not(bloqueado, out=bloqueado)
    hu[bloqueado] = np.float32(_HU_BLOQUEADO)
    del bloqueado
    solido = None
    hu -= np.float32(LIMIAR_HU)
    hu /= np.float32(_HU_POR_MM)
    return hu, corpo, lo, hi, direcao, dir_auto, avisos


def gerar(serie, caixa, modo="anatomico", espessura_mm=5, suavizacao_mm=1.0,
          direcao="auto", marcas=True, molde=False,
          casca_mm=CASCA_PADRAO_MM, abertura=ABERTURA_PADRAO):
    t0 = time.time()
    if modo not in MODOS:
        raise Recusa(u"Modo desconhecido: %s." % modo)
    t_casca = None
    if molde:
        try:
            t_casca = int(casca_mm)
        except Exception:
            raise Recusa(u"A casca do molde é um número inteiro de milímetros.")
        if float(casca_mm) != t_casca:
            raise Recusa(u"A casca do molde é um número inteiro de milímetros.")
        if not (CASCA_MIN_MM <= t_casca <= CASCA_MAX_MM):
            raise Recusa(u"Casca do molde fora da faixa: de %d a %d mm."
                         % (CASCA_MIN_MM, CASCA_MAX_MM))
        if abertura not in ABERTURAS:
            raise Recusa(u"Abertura do molde desconhecida: %s." % abertura)
    N = None
    if modo == "anatomico":
        try:
            N = int(espessura_mm)
        except Exception:
            raise Recusa(u"A espessura é um número inteiro de milímetros.")
        if float(espessura_mm) != N:
            raise Recusa(u"A espessura é um número inteiro de milímetros.")
        if not (ESPESSURA_MIN_MM <= N <= ESPESSURA_MAX_MM):
            raise Recusa(u"Espessura fora da faixa: de %d a %d mm."
                         % (ESPESSURA_MIN_MM, ESPESSURA_MAX_MM))
    sig = float(suavizacao_mm or 0.0)
    if not (0.0 <= sig <= SUAVIZACAO_MAX_MM):
        raise Recusa(u"Suavização fora da faixa: de 0 a %.0f mm."
                     % SUAVIZACAO_MAX_MM)
    cx = normalizar_caixa(serie, caixa)
    avisos = []

    import SimpleITK as sitk
    from scipy import ndimage

    margem = (N if modo == "anatomico" else 0) + 3.0 * sig + RELEVO_MM + 2.0
    if t_casca is not None:
        margem += t_casca + 1.0
    h, off, forma = _grade(serie, cx, margem, casca_mm=t_casca)
    if t_casca is not None and int(np.prod(forma)) > TETO_MOLDE_VOXELS:
        raise Recusa(u"Caixa grande demais para o molde: %.1f milhões de "
                     u"voxels a %.2f mm, e o teto do molde é %.0f milhões — "
                     u"a casca dobra a malha, e o molde não disputa memória "
                     u"com o contorno da noite. Diminua a caixa, ou gere o "
                     u"bólus sem o molde."
                     % (np.prod(forma) / 1e6, h, TETO_MOLDE_VOXELS / 1e6))
    Z, Y, X = forma
    J, corpo, lo, hi, direcao, dir_auto, av = campos_da_pele(
        serie, cx, h, off, forma, direcao)
    avisos.extend(av)
    pv = serie.previa

    E = _sdf_caixa(forma, lo, hi)
    E *= np.float32(h)
    if modo == "anatomico":
        dist = _distancia_fora(corpo, h)
        del corpo
        dist -= np.float32(N + 0.5 * h)
        np.maximum(dist, E, out=dist)
        E = dist
        del dist
    else:
        del corpo
    if sig > 0:
        ndimage.gaussian_filter(E, sigma=sig / h, mode="nearest", output=E)
    F = np.maximum(J, E)
    if not (F < 0).any():
        raise Recusa(u"Não sobrou bólus: a caixa não encosta na pele na "
                     u"direção de colocação, ou tudo nela é sólido.")

    if pv is not None and pv["mask"].any():
        xs = np.nonzero(pv["mask"].any(axis=(0, 1)))[0]
        centro_x = 0.5 * (xs.min() + xs.max()) * pv["sp"]
    else:
        centro_x = serie.extensao[0] / 2.0

    zona = np.zeros(F.shape, dtype=bool)
    rel_marcas = {"colocadas": False, "letra": u"", "seta": u"",
                  "entalhe": False, "motivo": u"desligadas"}
    if marcas:
        (an, sn), (au, su), (ar, sr) = _eixos_da_colocacao(direcao)
        tam_xyz = (X, Y, Z)

        def letra_por(ku, kr):
            p = [0.0, 0.0, 0.0]
            p[au] = ku if su > 0 else tam_xyz[au] - 1 - ku
            p[ar] = kr if sr > 0 else tam_xyz[ar] - 1 - kr
            if ar == 0 or au == 0:
                x_mm = off[0] + p[0] * h
            else:
                x_mm = off[0] + 0.5 * (X - 1) * h
            return u"R" if x_mm < centro_x else u"L"

        F, rel_marcas, zona = _marcas(F, h, direcao, letra_por)
        if not rel_marcas["colocadas"]:
            avisos.append(u"As marcas de lado não couberam (%s)."
                          % rel_marcas["motivo"])

    Fp = np.pad(F, 1, mode="constant", constant_values=1.0)
    del F
    r_rente = np.float32(RENTE_POR_GRADE * h)
    rente = np.abs(Fp) < r_rente
    Fp[rente] = r_rente
    del rente
    F = Fp[1:-1, 1:-1, 1:-1]
    mask = F < 0
    chaves_b = None
    if t_casca is not None:
        verts, faces, chaves_b = superficie(Fp, com_chaves=True)
    else:
        verts, faces = superficie(Fp)
    verts = verts - 1.0
    eixo_n, sinal_n = _NORMAL[direcao]
    folga_lat = sig / h + 2.0
    lo_a, hi_a = np.array(lo), np.array(hi)

    def lateral(v):
        ok = np.ones(len(v), dtype=bool)
        for e in range(3):
            if e == eixo_n:
                continue
            ok &= (v[:, e] > lo_a[e] + folga_lat) & (v[:, e] < hi_a[e] - folga_lat)
        return ok

    face_n = None
    if modo == "caixa":
        face_n = lo_a[eixo_n] if sinal_n < 0 else hi_a[eixo_n]
    esp = medir_espessura(verts, faces, J, E, zona, eixo_n, face_n, lateral, h)
    del J, E, zona
    if esp and modo == "anatomico" and esp["min"] < N - 1.0:
        avisos.append(u"A espessura mínima medida (%.1f mm) ficou abaixo da "
                      u"pedida — nas bordas, na sombra de saliências ou pela "
                      u"suavização. Confira antes de imprimir." % esp["min"])

    lps = serie.quadro_para_lps(off[None, :] + verts * h)
    faces_lps = faces[:, [0, 2, 1]] if np.linalg.det(serie.D) < 0 else faces
    malha = conferir_malha(lps, faces_lps)
    stl = stl_binario(lps, faces_lps)
    del lps, faces_lps

    def _para_indice(t):
        q = serie.lps_para_quadro(t.reshape(-1, 3)).reshape(-1, 3, 3)
        q -= off[None, None, :]
        q /= h
        return q

    volta, impares = voxelizar(_triangulos_do_stl(stl), mask.shape,
                               para_indice=_para_indice)
    dsc_volta = dsc(volta, mask)
    del volta

    res_molde = None
    if t_casca is not None:
        res_molde = _montar_molde(serie, Fp, verts, faces, chaves_b, off, h,
                                  t_casca, abertura, direcao, _para_indice,
                                  modo, rel_marcas)
    del faces, chaves_b

    rot, n_pecas = ndimage.label(mask, structure=np.ones((3, 3, 3)))
    del rot
    ext_q = off[None, :] + verts * h
    dims = (ext_q.max(0) - ext_q.min(0)) if len(verts) else np.zeros(3)
    del ext_q, verts
    previa = _previa_do_bolus(mask, off, h, F)
    return {
        "molde": res_molde,
        "modo": modo, "espessura_mm": N, "suavizacao_mm": sig,
        "direcao": direcao, "direcao_automatica": dir_auto, "grade_mm": h,
        "caixa": cx, "off": off.tolist(), "forma": list(forma),
        "malha": malha, "dsc_ida_volta": float(dsc_volta),
        "colunas_impares": int(impares), "pecas": int(n_pecas),
        "espessura": esp, "dimensoes_mm": [float(v) for v in dims],
        "volume_cm3": malha["volume_mm3"] / 1000.0, "marcas": rel_marcas,
        "face": parece_face(serie, cx), "avisos": avisos,
        "tempo_s": round(time.time() - t0, 2), "stl": stl,
        "mask": mask, "previa": previa,
    }


def _previa_do_bolus(mask, off, h, F=None, teto=2000000):
    if not mask.any():
        return {"mask": np.zeros((1, 1, 1), np.uint8),
                "densidade": np.zeros((1, 1, 1), np.uint8), "sp": h,
                "off": list(off), "forma": [1, 1, 1]}
    zz, yy, xx = np.nonzero(mask)
    lo = [max(0, zz.min() - 1), max(0, yy.min() - 1), max(0, xx.min() - 1)]
    hi = [min(mask.shape[0], zz.max() + 2), min(mask.shape[1], yy.max() + 2),
          min(mask.shape[2], xx.max() + 2)]
    fatia = (slice(lo[0], hi[0]), slice(lo[1], hi[1]), slice(lo[2], hi[2]))
    sub = mask[fatia]
    campo = F[fatia] if F is not None else np.where(sub, -1.0, 1.0)
    passo = max(1, int(math.ceil((sub.size / float(teto)) ** (1.0 / 3.0))))
    if passo > 1:
        sub = sub[::passo, ::passo, ::passo]
        campo = campo[::passo, ::passo, ::passo]
    o = [off[0] + lo[2] * h, off[1] + lo[1] * h, off[2] + lo[0] * h]
    return {"mask": np.ascontiguousarray(sub.astype(np.uint8)),
            "densidade": densidade_do_campo(campo),
            "sp": h * passo, "off": [float(v) for v in o],
            "forma": [int(sub.shape[2]), int(sub.shape[1]), int(sub.shape[0])]}


def resumo(res):
    def _sem_bytes(r):
        fora = {}
        for k, v in r.items():
            if k in ("stl", "mask", "previa", "molde"):
                continue
            fora[k] = v
        pv = r.get("previa") or {}
        fora["previa"] = {"sp": pv.get("sp"), "off": pv.get("off"),
                          "forma": pv.get("forma")}
        fora["bytes_stl"] = len(r.get("stl") or b"")
        return fora

    fora = _sem_bytes(res)
    fora["molde"] = _sem_bytes(res["molde"]) if res.get("molde") else None
    return fora



PLANOS = ("ax", "co", "sa")
COR_BOLUS = (181, 214, 90)
COR_MOLDE = (240, 176, 96)


def fatia(serie, plano, i):
    hu = serie.hu
    nx, ny, nz = serie.forma
    sx, sy, sz = serie.esp
    if plano == "ax":
        k = int(np.clip(i, 0, nz - 1))
        return np.asarray(hu[k]), (nx * sx, ny * sy), k
    if plano == "co":
        k = int(np.clip(i, 0, ny - 1))
        return np.asarray(hu[::-1, k, :]), (nx * sx, nz * sz), k
    if plano == "sa":
        k = int(np.clip(i, 0, nx - 1))
        return np.asarray(hu[::-1, :, k]), (ny * sy, nz * sz), k
    raise Recusa(u"Plano desconhecido: %s." % plano)


def _sobrepor(serie, plano, k, res, img, m=None, cor=COR_BOLUS, peso=0.55):
    m = res["mask"] if m is None else m
    off, h = np.array(res["off"]), float(res["grade_mm"])
    sx, sy, sz = serie.esp
    nx, ny, nz = serie.forma
    if plano == "ax":
        z = np.full((ny, nx), k * sz)
        y, x = np.meshgrid(np.arange(ny) * sy, np.arange(nx) * sx,
                           indexing="ij")
    elif plano == "co":
        zz = (nz - 1 - np.arange(nz)) * sz
        z, x = np.meshgrid(zz, np.arange(nx) * sx, indexing="ij")
        y = np.full(z.shape, k * sy)
    else:
        zz = (nz - 1 - np.arange(nz)) * sz
        z, y = np.meshgrid(zz, np.arange(ny) * sy, indexing="ij")
        x = np.full(z.shape, k * sx)
    iz = np.round((z - off[2]) / h).astype(np.int64)
    iy = np.round((y - off[1]) / h).astype(np.int64)
    ix = np.round((x - off[0]) / h).astype(np.int64)
    ok = ((iz >= 0) & (iz < m.shape[0]) & (iy >= 0) & (iy < m.shape[1]) &
          (ix >= 0) & (ix < m.shape[2]))
    sel = np.zeros(ok.shape, dtype=bool)
    sel[ok] = m[iz[ok], iy[ok], ix[ok]]
    cor = np.array(cor, dtype=np.float32)
    img[sel] = ((1.0 - peso) * img[sel] + peso * cor).astype(np.uint8)
    return img


def png_rgb(rgb):
    import zlib
    a = np.ascontiguousarray(np.asarray(rgb, dtype=np.uint8))
    alt, larg = a.shape[:2]
    linhas = b"".join(b"\x00" + a[y].tobytes() for y in range(alt))

    def bloco(tipo, dados):
        c = tipo + dados
        return (struct.pack(">I", len(dados)) + c
                + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + bloco(b"IHDR", struct.pack(">IIBBBBB", larg, alt, 8, 2, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas, 6))
            + bloco(b"IEND", b""))


JANELAS = {"pele": (-300.0, 1200.0), "partes_moles": (40.0, 400.0),
           "osso": (500.0, 2000.0)}


def corte_png(serie, plano, i, janela="pele", res=None):
    arr, _mm, k = fatia(serie, plano, i)
    c, l = JANELAS.get(janela, JANELAS["pele"])
    lo, hi = c - l / 2.0, c + l / 2.0
    g = (np.clip((arr.astype(np.float32) - lo) / (hi - lo), 0, 1) * 255.0)
    img = np.repeat(g.astype(np.uint8)[:, :, None], 3, axis=2)
    if res is not None:
        img = _sobrepor(serie, plano, k, res, img)
        if res.get("molde") and res["molde"].get("mask") is not None:
            img = _sobrepor(serie, plano, k, res, img, res["molde"]["mask"],
                            COR_MOLDE, 0.6)
    return png_rgb(img)


def sorteio():
    return os.urandom(8).hex()
