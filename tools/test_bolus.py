# -*- coding: utf-8 -*-
import ast
import io
import json
import math
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, ".."))
APP = os.path.join(RAIZ, "app")
sys.path.insert(0, APP)
sys.path.insert(0, AQUI)

import numpy as np
import SimpleITK as sitk

import _cleanup
import radai_bolus as B
import _componentes
OFICINA = _componentes.oficina("bolus", __file__)

VERBOSO = "-v" in sys.argv
_ok = [0]
_falhas = []


def checar(nome, cond, detalhe=u""):
    if cond:
        _ok[0] += 1
        if VERBOSO:
            print(u"  OK     %s" % nome)
    else:
        _falhas.append(nome)
        print(u"  FALHA  %s  %s" % (nome, str(detalhe).replace("\n", " ")[:200]))


def secao(t):
    print(u"\n-- %s %s" % (t, u"-" * max(0, 60 - len(t))))


def ler(rel):
    return io.open(_componentes.fonte(rel), encoding="utf-8").read()


R_CORPO = 80.0
C_SALIENCIA = np.array([-40.0, -math.sqrt(80.0 ** 2 - 40.0 ** 2), 30.0])
R_SALIENCIA = 15.0
C_CAVIDADE = np.array([30.0, -math.sqrt(80.0 ** 2 - 30.0 ** 2) + 3.0 + 8.0,
                       -20.0])
R_CAVIDADE = 8.0


def hu_fisico(p):
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    hu = np.full(len(p), -1000.0, dtype=np.float32)
    corpo = (x ** 2 + y ** 2 <= R_CORPO ** 2) & (np.abs(z) <= 80.0)
    sal = ((p - C_SALIENCIA) ** 2).sum(1) <= R_SALIENCIA ** 2
    cav = ((p - C_CAVIDADE) ** 2).sum(1) <= R_CAVIDADE ** 2
    hu[corpo | sal] = 20.0
    hu[cav] = -1000.0
    mesa = (y >= 86.0) & (y <= 90.0) & (np.abs(x) < 105.0)
    hu[mesa] = 300.0
    return hu


def rot(eixo, graus):
    a = math.radians(graus)
    c, s = math.cos(a), math.sin(a)
    if eixo == "x":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if eixo == "y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def fantoma(D=np.eye(3), esp=(1.0, 1.0, 3.0), forma=(200, 200, 50),
            sentinela=True):
    D = np.asarray(D, dtype=np.float64)
    esp = np.asarray(esp, dtype=np.float64)
    forma = [int(v) for v in forma]
    centro = (np.array(forma) - 1) / 2.0
    origem = -D.dot(centro * esp)
    X, Y, Z = forma
    k, j, i = np.meshgrid(np.arange(Z), np.arange(Y), np.arange(X),
                          indexing="ij")
    idx = np.stack([i, j, k], -1).reshape(-1, 3) * esp
    p = origem[None, :] + idx.dot(D.T)
    arr = hu_fisico(p).reshape(Z, Y, X).astype(np.int16)
    img = sitk.GetImageFromArray(arr)
    img.SetSpacing(tuple(esp))
    img.SetOrigin(tuple(origem))
    img.SetDirection(tuple(D.ravel()))
    if sentinela:
        img.SetMetaData("0010|0010", "ZZSENTINELA^PACIENTE")
    return img


def caixa_fisica(serie, lo, hi):
    cant = np.array([[a, b, c] for a in (lo[0], hi[0]) for b in (lo[1], hi[1])
                     for c in (lo[2], hi[2])], dtype=np.float64)
    q = serie.lps_para_quadro(cant)
    return {"x0": q[:, 0].min(), "x1": q[:, 0].max(), "y0": q[:, 1].min(),
            "y1": q[:, 1].max(), "z0": q[:, 2].min(), "z1": q[:, 2].max()}


def tri_lps(res):
    _c, t, _n = B.ler_stl(res["stl"])
    return t


def esfera_F(r=10.0, n=34, h=1.0, c=(0.3, -0.2, 0.1)):
    ax = (np.arange(n) - n / 2.0) * h
    z, y, x = np.meshgrid(ax, ax, ax, indexing="ij")
    return (np.sqrt((x - c[0]) ** 2 + (y - c[1]) ** 2 + (z - c[2]) ** 2)
            - r).astype(np.float32)


def teste_superficie():
    secao(u"a superfície: tetraedros de Kuhn, fechada e para fora")
    F = np.pad(esfera_F(), 1, constant_values=1.0)
    v, f = B.superficie(F)
    m = B.conferir_malha(v, f)
    checar(u"esfera: malha fechada e manifold", m["fechada"], m)
    ideal = 4.0 / 3.0 * math.pi * 10.0 ** 3
    checar(u"esfera: volume a 1,5%% do ideal (%.0f contra %.0f)"
           % (m["volume_mm3"], ideal),
           abs(m["volume_mm3"] - ideal) / ideal < 0.015, m["volume_mm3"])
    checar(u"esfera: as normais saem (volume assinado positivo)",
           m["volume_mm3"] > 0)
    centro = v.mean(0)
    tri = v[f]
    nrm = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    fora = ((tri.mean(1) - centro) * nrm).sum(1)
    checar(u"esfera: TODO triângulo aponta para fora do centro",
           bool((fora > 0).all()), int((fora <= 0).sum()))

    n, h = 48, 1.0
    ax = (np.arange(n) - n / 2.0) * h
    z, y, x = np.meshgrid(ax, ax, ax, indexing="ij")
    Rt, rt = 13.0, 5.0
    Ft = (np.sqrt((np.sqrt(x ** 2 + y ** 2) - Rt) ** 2 + z ** 2) - rt)
    v2, f2 = B.superficie(np.pad(Ft.astype(np.float32), 1, constant_values=1.0))
    m2 = B.conferir_malha(v2, f2)
    ideal2 = 2 * math.pi ** 2 * Rt * rt ** 2
    checar(u"toro: fechado", m2["fechada"], m2)
    checar(u"toro: volume a 2% do ideal",
           abs(m2["volume_mm3"] - ideal2) / ideal2 < 0.02,
           (m2["volume_mm3"], ideal2))
    arestas = lambda ff: len(np.unique(np.sort(np.concatenate(
        [ff[:, [0, 1]], ff[:, [1, 2]], ff[:, [2, 0]]]), axis=1), axis=0))
    chi_e = len(v) - arestas(f) + len(f)
    chi_t = len(v2) - arestas(f2) + len(f2)
    checar(u"a característica de Euler: 2 na esfera, 0 no toro",
           chi_e == 2 and chi_t == 0, (chi_e, chi_t))

    m3 = B.conferir_malha(v, f[1:])
    checar(u"(isca) tirar UM triângulo abre a malha, e ela acusa",
           not m3["fechada"] and m3["arestas_sem_par"] == 3, m3)
    f4 = f.copy()
    f4[0] = f4[0][[0, 2, 1]]
    m4 = B.conferir_malha(v, f4)
    checar(u"(isca) virar UM triângulo quebra a orientação, e ela acusa",
           not m4["fechada"] and m4["arestas_repetidas"] > 0, m4)
    ve = v * np.array([-1.0, 1.0, 1.0])
    checar(u"(isca) espelhar sem reorientar dá volume NEGATIVO",
           B.volume_assinado(ve, f) < 0)


def teste_ponto_triangulo():
    secao(u"a distância ponto–triângulo que mede a espessura é exata")
    rng = np.random.default_rng(7)
    a = rng.normal(size=(400, 3)) * 3
    b = a + rng.normal(size=(400, 3)) * 3
    c = a + rng.normal(size=(400, 3)) * 3
    p = rng.normal(size=(400, 3)) * 6
    d = B._ponto_triangulo(p, a, b, c)
    u = rng.random((20000, 2))
    fora = u.sum(1) > 1
    u[fora] = 1 - u[fora]
    pior = 0.0
    for i in range(0, 400, 20):
        q = a[i] + u[:, :1] * (b[i] - a[i]) + u[:, 1:] * (c[i] - a[i])
        bruto = np.linalg.norm(q - p[i], axis=1).min()
        pior = max(pior, d[i] - bruto)
        if d[i] > bruto + 1e-9:
            break
    checar(u"nunca maior que a força bruta, e a menos de 0,05 do mínimo dela",
           pior <= 1e-9 and all(
               d[i] <= np.linalg.norm(
                   a[i] + u[:, :1] * (b[i] - a[i]) + u[:, 1:] * (c[i] - a[i])
                   - p[i], axis=1).min() + 1e-9 for i in range(0, 400, 20)),
           pior)
    t0 = np.array([[0.0, 0, 0]]); t1 = np.array([[4.0, 0, 0]])
    t2 = np.array([[0.0, 4, 0]])
    checar(u"acima do interior, a distância é a altura",
           abs(B._ponto_triangulo(np.array([[1.0, 1, 3]]), t0, t1, t2)[0]
               - 3.0) < 1e-12)
    checar(u"fora da quina, a distância é ao vértice",
           abs(B._ponto_triangulo(np.array([[-3.0, -4, 0]]), t0, t1, t2)[0]
               - 5.0) < 1e-12)
    plano = abs(np.array([[-3.0, -4, 0]])[0, 2])
    checar(u"(isca) a distância ao plano erraria o ponto da quina",
           abs(plano - 5.0) > 1)
    k = np.array([5, 3, 5, 9, 3, 3, 1], dtype=np.int64)
    prim, inv = B._unicos(k)
    checar(u"`_unicos`: um índice por valor, e a inversa reconstrói",
           sorted(k[prim].tolist()) == [1, 3, 5, 9]
           and (k[prim][inv] == k).all())


def teste_voxelizar():
    secao(u"a volta malha → voxel, por paridade de raio")
    F = np.pad(esfera_F(r=9.3), 1, constant_values=1.0)
    v, f = B.superficie(F)
    vol, imp = B.voxelizar(v[f], F.shape)
    d = B.dsc(vol, F < 0)
    checar(u"a esfera volta INTEIRA (DSC %.6f)" % d, d == 1.0 and imp == 0,
           (d, imp))
    cal = v[f].mean(1)[:, 2] < v[:, 2].max() - 3.0
    vol2, imp2 = B.voxelizar(v[f[cal]], F.shape)
    checar(u"(isca) malha sem a calota deixa coluna com cruzamento ímpar",
           imp2 > 10, imp2)


def teste_stl():
    secao(u"o STL binário")
    F = np.pad(esfera_F(), 1, constant_values=1.0)
    v, f = B.superficie(F)
    dados = B.stl_binario(v + 100.0, f)
    checar(u"84 + 50 bytes por triângulo", len(dados) == 84 + 50 * len(f))
    cab, t, n = B.ler_stl(dados)
    checar(u"o cabeçalho NÃO começa com «solid»",
           not cab.lstrip().lower().startswith(b"solid"), cab[:20])
    checar(u"e diz que é rascunho não aprovado", b"DRAFT UNAPPROVED" in cab)
    checar(u"`cabecalho_seguro` aprova o nosso", B.cabecalho_seguro(cab))
    checar(u"(isca) e reprova um que começa com «solid»",
           not B.cabecalho_seguro(b"solid bolus".ljust(80, b" ")))
    checar(u"(isca) e um sem a marca de rascunho",
           not B.cabecalho_seguro(b"bolus".ljust(80, b" ")))
    checar(u"os vértices voltam em float32 (erro < 1e-4 mm)",
           np.abs(t - (v + 100.0)[f]).max() < 1e-4)
    comp = np.linalg.norm(n, axis=1)
    checar(u"normais unitárias", np.abs(comp - 1).max() < 1e-5)
    fora = ((t.mean(1) - (v + 100.0).mean(0)) * n).sum(1)
    checar(u"e para fora", bool((fora > 0).all()))


def _canonica(v, f):
    t = np.round(np.asarray(v, dtype=np.float64)[np.asarray(f)], 6)
    out = []
    for tri in t:
        k = min(range(3), key=lambda i: tuple(tri[i]))
        out.append(tuple(map(tuple, np.roll(tri, -k, axis=0))))
    return sorted(out)


def teste_em_fatias():
    secao(u"a superfície em fatias e os passos em bloco: a MESMA malha")
    F = np.pad(esfera_F(), 1, constant_values=1.0)
    Z, Y, X = F.shape
    v0, f0 = B.superficie(F, celulas_por_fatia=10 ** 9)
    c0 = _canonica(v0, f0)
    for cpf in (4000, 1200):
        v1, f1 = B.superficie(F, celulas_por_fatia=cpf)
        n = int(math.ceil((Z - 1) / float(max(1, cpf // ((Y - 1) * (X - 1))))))
        checar(u"em %d fatias: os mesmos vértices e os mesmos triângulos "
               u"orientados" % n, n > 5 and np.array_equal(v0, v1)
               and _canonica(v1, f1) == c0, (n, len(v0), len(v1)))
        checar(u"   e a malha costurada fecha",
               B.conferir_malha(v1, f1)["fechada"])
    v1, f1 = B.superficie(F, celulas_por_fatia=1200)
    k = int(f1[0, 0])
    v2 = np.vstack([v1, v1[k:k + 1]])
    f2 = f1.copy()
    f2[0, 0] = len(v1)
    m2 = B.conferir_malha(v2, f2)
    checar(u"(isca) um vértice de costura duplicado abre a malha, e ela acusa",
           not m2["fechada"] and m2["arestas_sem_par"] > 0, m2)

    ref_stl = B.stl_binario(v0 + 50.0, f0)
    ref_m = B.conferir_malha(v0, f0)
    ref_vox = B.voxelizar((v0)[f0], F.shape)
    antes = B.BLOCO_TRIANGULOS
    try:
        B.BLOCO_TRIANGULOS = 997
        stl_b = B.stl_binario(v0 + 50.0, f0)
        m_b = B.conferir_malha(v0, f0)
        vox_b = B.voxelizar(v0[f0], F.shape)
        f_isca = f0.copy()
        f_isca[1500] = f_isca[1500][[0, 2, 1]]
        m_isca = B.conferir_malha(v0, f_isca)
    finally:
        B.BLOCO_TRIANGULOS = antes
    checar(u"STL em blocos de 997: os mesmos bytes", stl_b == ref_stl)
    checar(u"conferência em blocos: o mesmo laudo",
           m_b["fechada"] and m_b["triangulos"] == ref_m["triangulos"]
           and abs(m_b["volume_mm3"] - ref_m["volume_mm3"]) < 1e-6, m_b)
    checar(u"(isca) e em blocos ela ainda acusa um triângulo virado FORA do "
           u"primeiro bloco", not m_isca["fechada"]
           and m_isca["arestas_repetidas"] > 0, m_isca)
    checar(u"voxelizar em blocos: a mesma máscara",
           np.array_equal(vox_b[0], ref_vox[0]) and vox_b[1] == 0)
    t32 = B._triangulos_do_stl(ref_stl)
    checar(u"a vista do STL não copia (é float32 sobre os bytes)",
           t32.dtype == np.float32 and not t32.flags.owndata)
    vol, imp = B.voxelizar(t32, F.shape, para_indice=lambda t: t - 50.0)
    checar(u"e a volta por ela dá a mesma máscara (DSC %.6f)"
           % B.dsc(vol, ref_vox[0]), B.dsc(vol, ref_vox[0]) == 1.0 and imp == 0)


def teste_distancia_float32():
    secao(u"a distância em float32 (ITK) é a do scipy")
    from scipy import ndimage
    rng = np.random.default_rng(11)
    m = np.zeros((36, 44, 52), dtype=bool)
    m[8:28, 10:34, 14:40] = True
    m[3:6, 3:7, 3:7] = True
    m &= rng.random(m.shape) > 0.04
    for h in (1.0, 0.75, 0.5):
        d0 = ndimage.distance_transform_edt(~m, sampling=(h, h, h))
        d1 = B._distancia_fora(m, h)
        checar(u"passo %.2f mm: a menos de 1e-4 mm do scipy (%.1e)"
               % (h, np.abs(d1 - d0).max()),
               d1.dtype == np.float32 and np.abs(d1 - d0).max() < 1e-4)
    import SimpleITK as sitk
    im = sitk.GetImageFromArray(m.view(np.uint8))
    bruto = sitk.GetArrayFromImage(sitk.SignedMaurerDistanceMap(
        im, insideIsPositive=False, squaredDistance=False,
        useImageSpacing=True))
    d0 = ndimage.distance_transform_edt(~m)
    checar(u"(isca) o mapa com sinal, sem o piso, NÃO é a distância de fora",
           np.abs(bruto - d0).max() > 1.0)


def _img_teste(D, tipo="i16", deslocar=0.0):
    import SimpleITK as sitk
    rng = np.random.default_rng(5)
    a = rng.integers(-1000, 1500, (7, 9, 11)).astype(np.float32) + deslocar
    img = sitk.GetImageFromArray(a.astype(np.int16) if tipo == "i16" else a)
    img.SetSpacing((0.7, 0.9, 2.5))
    img.SetOrigin((10.0, -20.0, 30.0))
    img.SetDirection(tuple(np.asarray(D, dtype=np.float64).ravel()))
    return img


def _mesma_imagem(a, b):
    import SimpleITK as sitk
    return (a.GetPixelID() == b.GetPixelID()
            and np.array_equal(sitk.GetArrayViewFromImage(a),
                               sitk.GetArrayViewFromImage(b))
            and np.allclose(a.GetDirection(), b.GetDirection(), atol=1e-12)
            and np.allclose(a.GetOrigin(), b.GetOrigin(), atol=1e-9)
            and np.allclose(a.GetSpacing(), b.GetSpacing()))


def teste_serie_sem_copia():
    secao(u"abrir: sem cópia em int16/LPS, um espelho só, e o teto da série")
    import SimpleITK as sitk
    orient = sitk.DICOMOrientImageFilter.GetOrientationFromDirectionCosines
    hfs = _img_teste(np.eye(3))
    checar(u"TC em int16 e em LPS: nenhuma cópia (volta a MESMA imagem)",
           B._int16_lps(hfs) is hfs)
    casos = (("pés primeiro", np.diag([-1.0, 1.0, -1.0])),
             ("decúbito ventral", np.diag([-1.0, -1.0, 1.0])),
             ("ventral, pés primeiro", np.diag([1.0, -1.0, -1.0])),
             ("oblíqua, pés primeiro",
              np.diag([-1.0, 1.0, -1.0]).dot(rot("z", 11))))
    for nome, D in casos:
        img = _img_teste(D)
        ref = sitk.DICOMOrient(img, "LPS")
        checar(u"%s: o espelho é o do DICOMOrient (pixel, origem, direção)"
               % nome, _mesma_imagem(B._int16_lps(img), ref))
    img = _img_teste(np.diag([-1.0, 1.0, -1.0]))
    checar(u"(isca) a série pés-primeiro SEM espelhar não é a do DICOMOrient",
           not _mesma_imagem(img, sitk.DICOMOrient(img, "LPS")))
    sag = _img_teste(np.array([[0.0, 0, 1], [1, 0, 0], [0, 1, 0]]))
    o = B._int16_lps(sag)
    checar(u"eixos trocados (sagital): cai no DICOMOrient e sai LPS",
           orient(o.GetDirection()) == "LPS"
           and _mesma_imagem(o, sitk.DICOMOrient(sag, "LPS")))
    f32 = _img_teste(np.eye(3), "f32", deslocar=-2500.0)
    o = B._int16_lps(f32)
    arr = sitk.GetArrayViewFromImage(o)
    checar(u"float32 abaixo de −1024 vira int16 com o piso",
           o.GetPixelID() == sitk.sitkInt16 and arr.min() == -1024
           and np.array_equal(arr, np.clip(np.round(
               sitk.GetArrayViewFromImage(f32)), -1024, 32000)
               .astype(np.int16)), (o.GetPixelIDTypeAsString(), arr.min()))
    checar(u"no teto, passa", B.conferir_tamanho_da_serie(B.TETO_SERIE_VOXELS))
    try:
        B.conferir_tamanho_da_serie(B.TETO_SERIE_VOXELS + 1)
        m = None
    except B.Recusa as e:
        m = str(e)
    checar(u"um voxel acima, recusa dizendo o tamanho",
           m and u"grande demais" in m and u"milhões" in m, m)
    antes = B.TETO_SERIE_VOXELS
    lido = []
    try:
        B.TETO_SERIE_VOXELS = 100
        try:
            B.abrir(lambda: lido.append(1) or _img_teste(np.eye(3)), "CT")
            m = None
        except B.Recusa as e:
            m = str(e)
    finally:
        B.TETO_SERIE_VOXELS = antes
    checar(u"`abrir` recusa a série acima do teto (pelo carregador)",
           m and u"grande demais" in m and lido == [1], m)


def teste_eixos_da_marca():
    secao(u"os eixos da marca: direita × cima = para fora, nas seis")
    for d in B.DIRECOES:
        (an, sn), (au, su), (ar, sr) = B._eixos_da_colocacao(d)
        n = np.zeros(3); n[an] = sn
        u = np.zeros(3); u[au] = su
        r = np.zeros(3); r[ar] = sr
        checar(u"`%s`: r × u = n (visto de fora, a letra não sai espelhada)"
               % d, np.allclose(np.cross(r, u), n), (r, u, n))
    L, A, S = np.array([1., 0, 0]), np.array([0., -1, 0]), np.array([0., 0, 1])
    checar(u"(isca) o referencial canhoto do DeFace reprova a mesma conta",
           not np.allclose(np.cross(L, A), S))
    (_a, _s), (_u, _su), (ar, sr) = B._eixos_da_colocacao("ant")
    checar(u"de frente, a direita da tela é a ESQUERDA do paciente (+x)",
           ar == 0 and sr == 1)


def teste_quadro_e_matriz(series):
    secao(u"o quadro vai para LPS pela matriz de direção INTEIRA")
    rng = np.random.default_rng(3)
    for nome, s in series.items():
        idx = rng.random((20, 3)) * (np.array(s.forma) - 1)
        esperado = np.array([s.img.TransformContinuousIndexToPhysicalPoint(
            [float(a) for a in p]) for p in idx])
        obtido = s.quadro_para_lps(idx * s.esp)
        checar(u"%s: igual ao TransformContinuousIndexToPhysicalPoint" % nome,
               np.abs(esperado - obtido).max() < 1e-6,
               np.abs(esperado - obtido).max())
        volta = s.lps_para_quadro(obtido)
        checar(u"%s: e a volta fecha" % nome,
               np.abs(volta - idx * s.esp).max() < 1e-6)
        checar(u"%s: a série reorientada é própria (det = +1)" % nome,
               abs(np.linalg.det(s.D) - 1.0) < 1e-6, np.linalg.det(s.D))


def teste_corte_na_orientacao_de_leitura(series):
    secao(u"o corte sai na orientação de leitura, em qualquer aquisição")
    for nome in ("HFS", "FFS", "impropria"):
        s = series[nome]
        q = s.lps_para_quadro(np.array([[-40.0, -80.0, 30.0],
                                        [40.0, -80.0, 30.0]]))
        k = int(round(q[0, 2] / s.esp[2]))
        arr, _mm, _k = B.fatia(s, "ax", k)
        lin = int(round(q[0, 1] / s.esp[1]))
        c_dir = int(round(q[0, 0] / s.esp[0]))
        c_esq = int(round(q[1, 0] / s.esp[0]))
        checar(u"%s: axial — a saliência na metade ESQUERDA da tela "
               u"(direita do paciente)" % nome,
               arr[lin, c_dir] > -300 and arr[lin, c_esq] < -300
               and c_dir < arr.shape[1] / 2, (arr[lin, c_dir], arr[lin, c_esq]))
        checar(u"%s: e na metade de CIMA (anterior)" % nome,
               lin < arr.shape[0] / 2, lin)
        arr2, _mm, _k = B.fatia(s, "co", int(round(q[0, 1] / s.esp[1])))
        lin2 = (s.forma[2] - 1) - k
        checar(u"%s: coronal — a saliência na metade de CIMA (superior)"
               % nome, arr2[lin2, c_dir] > -300 and lin2 < arr2.shape[0] / 2,
               (lin2, arr2.shape))


LO_ANAT = (-92.0, -104.0, -60.0)
HI_ANAT = (92.0, -35.0, 60.0)
LO_MEDIA = (-62.0, -104.0, -44.0)
HI_MEDIA = (62.0, -35.0, 44.0)

P_SALIENCIA = np.array([[-40.0, C_SALIENCIA[1] - R_SALIENCIA - 2.5, 30.0]])
P_ESPELHO_X = np.array([[40.0, C_SALIENCIA[1] - R_SALIENCIA - 2.5, 30.0]])
P_ESPELHO_Z = np.array([[-40.0, C_SALIENCIA[1] - R_SALIENCIA - 2.5, -30.0]])
P_CAMADA_ESQ = np.array([[40.0, -math.sqrt(80 ** 2 - 40 ** 2) - 2.5, 30.0]])
P_REENTRANCIA = np.array([[-54.5, -62.0, 30.0]])
P_CAVIDADE = C_CAVIDADE[None, :]


def _checar_fisico(nome, res, rotulo=u""):
    t = tri_lps(res)
    dentro = B.dentro_da_malha(t, np.concatenate(
        [P_SALIENCIA, P_ESPELHO_X, P_ESPELHO_Z, P_CAMADA_ESQ, P_REENTRANCIA,
         P_CAVIDADE]))
    checar(u"%s%s: o ponto sobre a saliência (direita, em cima) está no "
           u"bólus" % (nome, rotulo), dentro[0])
    checar(u"%s%s: o mesmo ponto espelhado em x NÃO está" % (nome, rotulo),
           not dentro[1])
    checar(u"%s%s: nem espelhado em z" % (nome, rotulo), not dentro[2])
    checar(u"%s%s: a camada do lado esquerdo existe" % (nome, rotulo),
           dentro[3])
    checar(u"%s%s: a reentrância atrás da saliência NÃO vira bólus"
           % (nome, rotulo), not dentro[4])
    checar(u"%s%s: a cavidade de ar dentro do corpo NÃO vira bólus"
           % (nome, rotulo), not dentro[5])
    return t


def teste_bolus_anatomico(series):
    secao(u"anatômico, 5 mm: fechado, no lugar, e com a espessura medida")
    guardado = {}
    for nome, s in series.items():
        cx = caixa_fisica(s, LO_MEDIA, HI_MEDIA)
        t0 = time.time()
        res = B.gerar(s, cx, "anatomico", 5, 0.0, "auto", marcas=False)
        dt = time.time() - t0
        m = res["malha"]
        print(u"         · %s: %.1f s, %d triângulos, grade %.2f mm, espessura "
              u"%.2f/%.2f/%.2f mm" % (nome, dt, m["triangulos"],
                                      res["grade_mm"], res["espessura"]["min"],
                                      res["espessura"]["mediana"],
                                      res["espessura"]["max"]))
        checar(u"%s: malha fechada" % nome, m["fechada"], m)
        checar(u"%s: normais para fora EM LPS (volume > 0)" % nome,
               m["volume_mm3"] > 0, m["volume_mm3"])
        checar(u"%s: a volta STL → voxel é exata (DSC %.5f)"
               % (nome, res["dsc_ida_volta"]),
               res["dsc_ida_volta"] >= 0.9999 and res["colunas_impares"] == 0,
               (res["dsc_ida_volta"], res["colunas_impares"]))
        checar(u"%s: a direção automática achou a frente" % nome,
               res["direcao"] == "ant" and res["direcao_automatica"],
               res["direcao"])
        checar(u"%s: grade ≤ 1 mm e dentro do teto" % nome,
               res["grade_mm"] <= 1.0 and
               int(np.prod(res["forma"])) <= B.TETO_POR_GRADE[res["grade_mm"]],
               (res["grade_mm"], res["forma"]))
        e = res["espessura"]
        checar(u"%s: espessura mediana de 5 mm (%.2f)" % (nome, e["mediana"]),
               4.6 <= e["mediana"] <= 5.4, e)
        checar(u"%s: e medida em muitos pontos (%d)" % (nome, e["n"]),
               e["n"] > 2000)
        _checar_fisico(nome, res)
        guardado[nome] = res
    return guardado


def teste_espelho_do_stl(res):
    secao(u"(isca) o STL espelhado é pego pela mesma pergunta física")
    t = tri_lps(res) * np.array([-1.0, 1.0, 1.0])
    d = B.dentro_da_malha(t, np.concatenate([P_SALIENCIA, P_ESPELHO_X]))
    checar(u"espelhado, o ponto da saliência sai do bólus e o espelho entra",
           (not d[0]) and d[1], d)


def teste_suavizacao(series, r0):
    secao(u"suavização: só a face externa, e a espessura continua medida")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MEDIA, HI_MEDIA)
    checar(u"a referência sem suavizar é da mesma caixa e da frente",
           r0["suavizacao_mm"] == 0.0 and r0["direcao"] == "ant"
           and r0["caixa"] == B.normalizar_caixa(s, cx))
    r2 = B.gerar(s, cx, "anatomico", 5, 2.5, "ant", marcas=False)
    checar(u"suavizado continua fechado", r2["malha"]["fechada"])
    checar(u"a mediana continua perto de 5 mm (%.2f)"
           % r2["espessura"]["mediana"],
           4.4 <= r2["espessura"]["mediana"] <= 5.6, r2["espessura"])
    fora, dentro = [], []
    for x in (-20.0, 10.0, 55.0):
        for z in (-40.0, 0.0):
            fora.append([x, -math.sqrt(80.5 ** 2 - x ** 2), z])
            dentro.append([x, -math.sqrt(79.0 ** 2 - x ** 2), z])
    for nome, r in ((u"sem suavizar", r0), (u"suavizado 2,5 mm", r2)):
        t = tri_lps(r)
        a = B.dentro_da_malha(t, np.array(fora))
        b = B.dentro_da_malha(t, np.array(dentro))
        checar(u"%s: 0,5 mm fora da pele é bólus (sem vão de ar)" % nome,
               bool(a.all()), a)
        checar(u"%s: 1 pixel dentro da pele não é (sem interferência)" % nome,
               not b.any(), b)
    v0, v2 = r0["malha"]["volume_mm3"], r2["malha"]["volume_mm3"]
    checar(u"a suavização muda o volume em menos de 15%% (%.1f → %.1f cm³)"
           % (v0 / 1000.0, v2 / 1000.0), abs(v2 - v0) < 0.15 * v0)
    return r0


def teste_marcas(series):
    secao(u"as marcas de lado: letra e seta legíveis de fora, entalhe no canto")
    for nome in ("HFS", "FFS", "obliqua"):
        s = series[nome]
        cx = caixa_fisica(s, (-66.0, -104.0, 2.0), (-4.0, -45.0, 58.0))
        rf = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False)
        rt = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=True)
        checar(u"%s: as duas gerações usam a mesma grade" % nome,
               rf["off"] == rt["off"] and rf["forma"] == rt["forma"])
        mk = rt["marcas"]
        checar(u"%s: as marcas foram colocadas" % nome, mk["colocadas"], mk)
        checar(u"%s: e o entalhe cortou alguma coisa" % nome, mk["entalhe"])
        checar(u"%s: e a malha continua fechada" % nome,
               rt["malha"]["fechada"])
        h, off = rt["grade_mm"], np.array(rt["off"])

        def lps_de(m):
            zz, yy, xx = np.nonzero(m)
            q = off[None, :] + np.stack([xx, yy, zz], 1) * h
            return s.quadro_para_lps(q)

        relevo = lps_de(rt["mask"] & ~rf["mask"])
        entalhe = lps_de(rf["mask"] & ~rt["mask"])
        todo = lps_de(rf["mask"])
        checar(u"%s: há relevo (%d voxels)" % (nome, len(relevo)),
               len(relevo) > 30)
        lado = u"R" if relevo[:, 0].mean() < 0 else u"L"
        checar(u"%s: a letra «%s» bate com o lado físico da marca (x=%.0f)"
               % (nome, mk["letra"], relevo[:, 0].mean()),
               mk["letra"] == lado)
        x = relevo.dot(s.D[:, 0])
        z = relevo.dot(s.D[:, 2])
        bm = B._bitmap(mk["letra"] + u"^").astype(float)
        H_, W_ = bm.shape
        cel = max(1, int(round(B.CELULA_MM / h))) * h
        x0, z1 = x.min(), z.max()
        amostra = np.zeros((H_, W_))
        ci = np.clip(((z1 - z) / cel).astype(int), 0, H_ - 1)
        cj = np.clip(((x - x0) / cel).astype(int), 0, W_ - 1)
        np.add.at(amostra, (ci, cj), 1.0)
        P = amostra > 0

        def iou(a, b):
            return (a & b).sum() / float(max(1, (a | b).sum()))

        certo = iou(P, bm > 0)
        espelho = iou(P, (bm > 0)[:, ::-1])
        checar(u"%s: o relevo lê «%s↑» de fora (IoU %.2f) melhor que "
               u"espelhado (%.2f)" % (nome, mk["letra"], certo, espelho),
               certo >= 0.55 and certo > espelho + 0.15, (certo, espelho))
        checar(u"%s: o entalhe está no canto superior-DIREITO do paciente"
               % nome, len(entalhe) > 0 and entalhe[:, 0].mean() < todo[:, 0].mean()
               and entalhe[:, 2].mean() > todo[:, 2].mean(),
               (entalhe[:, 0].mean() if len(entalhe) else None,
                todo[:, 0].mean()))


def teste_modo_caixa(series):
    secao(u"modo Caixa: o bloco que encaixa, sem reentrância")
    s = series["HFS"]
    cx = caixa_fisica(s, (-72.0, -104.0, 5.0), (-8.0, -55.0, 55.0))
    res = B.gerar(s, cx, "caixa", 5, 1.0, "ant", marcas=False)
    checar(u"fechado", res["malha"]["fechada"], res["malha"])
    checar(u"volta exata", res["dsc_ida_volta"] >= 0.9999)
    t = tri_lps(res)
    d = B.dentro_da_malha(t, np.array([[-40.0, -95.0, 30.0],
                                       [-40.0, C_SALIENCIA[1] - 17.0, 30.0],
                                       P_REENTRANCIA[0]]))
    checar(u"a frente da caixa é bólus", d[0])
    checar(u"e o ar colado na saliência também", d[1])
    checar(u"a reentrância atrás da saliência NÃO é (ele sai do paciente)",
           not d[2])
    e = res["espessura"]
    checar(u"a espessura foi medida na face da caixa", e and e["n"] > 100, e)

    r1 = B.gerar(s, cx, "caixa", 1, 1.0, "ant", marcas=False)
    r30 = B.gerar(s, cx, "caixa", 30, 1.0, "ant", marcas=False)
    checar(u"N = 1 e N = 30: o mesmo STL, byte a byte (a N não entra)",
           r1["stl"] == r30["stl"])
    checar(u"e o resultado não afirma espessura pedida (None)",
           r1["espessura_mm"] is None and r30["espessura_mm"] is None)
    sorteio = u"0123456789abcdef"
    n1, n30 = B.nome_do_stl(r1, sorteio), B.nome_do_stl(r30, sorteio)
    med = int(round(r1["espessura"]["mediana"]))
    checar(u"o nome não depende da N, e leva a mediana MEDIDA (%s)" % n1,
           n1 == n30 and (u"box_measured%dmm" % med) in n1, (n1, n30))
    velho = lambda n: u"RadAI_bolus_DRAFT_box_%dmm_%s.stl" % (n, sorteio[:8])
    checar(u"(isca) o nome feito da N, como era, reprova a mesma comparação",
           velho(1) != velho(30))
    linha = B.linha_do_ato(r30, n30)
    checar(u"o registro do ato diz «sem camada pedida» e não «30 mm»",
           u"sem camada pedida" in linha and u"30 mm" not in linha, linha)
    checar(u"a N nem é conferida no modo Caixa (o campo vem vazio da tela)",
           B.gerar(s, cx, "caixa", None, 1.0, "ant", marcas=False)["stl"]
           == r1["stl"])
    checar(u"no Anatômico o nome continua com a camada pedida",
           B.nome_do_arquivo("anatomico", 5, sorteio)
           == u"RadAI_bolus_DRAFT_anatomical_5mm_01234567.stl")
    checar(u"e no Caixa sem medida, nenhum número",
           B.nome_do_arquivo("caixa", None, sorteio)
           == u"RadAI_bolus_DRAFT_box_01234567.stl")


def teste_matriz_impropria(series):
    secao(u"(guarda) matriz de direção imprópria não inverte as normais")
    s = series["HFS"]
    cx = caixa_fisica(s, (-72.0, -104.0, 5.0), (-8.0, -55.0, 55.0))
    import copy
    s2 = copy.copy(s)
    s2.D = s.D.dot(np.diag([1.0, 1.0, -1.0]))
    res = B.gerar(s2, cx, "caixa", 5, 0.0, "ant", marcas=False)
    checar(u"com det(D) = −1 o volume em LPS continua positivo",
           res["malha"]["volume_mm3"] > 0 and res["malha"]["fechada"],
           res["malha"])


def teste_sem_phi(series):
    secao(u"nada da série entra no STL")
    s = series["HFS"]
    cx = caixa_fisica(s, (-72.0, -104.0, 5.0), (-8.0, -55.0, 55.0))
    res = B.gerar(s, cx, "caixa", 5, 0.0, "ant", marcas=False)
    checar(u"o nome de mentira da série não está nos bytes",
           b"ZZSENTINELA" not in res["stl"])
    checar(u"o cabeçalho é a constante, e só ela",
           res["stl"][:80] == B.CABECALHO_STL[:80].ljust(80, b" "))
    nome = B.nome_do_arquivo("anatomico", 5, u"a1b2c3d4e5f6a7b8")
    checar(u"o nome do arquivo: modo, espessura e sorteio (%s)" % nome,
           nome == u"RadAI_bolus_DRAFT_anatomical_5mm_a1b2c3d4.stl")
    nome2 = B.nome_do_arquivo("caixa", 7, u"../BELTRANO^ISCA 1.2.840/xy")
    checar(u"(isca) sorteio com texto estranho não passa para o nome",
           u"BELTRANO" not in nome2 and u"/" not in nome2 and u"." not in
           nome2[:-4], nome2)
    r = B.resumo(res)
    checar(u"o resumo não leva malha, máscara nem bytes",
           "stl" not in r and "mask" not in r and
           "mask" not in (r.get("previa") or {}))
    json.dumps(r)
    checar(u"e é JSON", True)


def teste_recusas(series):
    secao(u"o que o módulo recusa, e diz por quê")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_ANAT, HI_ANAT)

    def recusa(f, *a, **k):
        try:
            f(*a, **k)
        except B.Recusa as e:
            return str(e)
        return None

    checar(u"RM é recusada", recusa(B.conferir_modalidade, "MR"))
    checar(u"PET também", recusa(B.conferir_modalidade, "PT"))
    checar(u"TC passa", recusa(B.conferir_modalidade, "CT") is None)
    checar(u"espessura quebrada é recusada (mm inteiros)",
           recusa(B.gerar, s, cx, "anatomico", 5.5))
    checar(u"espessura zero é recusada", recusa(B.gerar, s, cx, "anatomico", 0))
    checar(u"acima de %d mm é recusada" % B.ESPESSURA_MAX_MM,
           recusa(B.gerar, s, cx, "anatomico", B.ESPESSURA_MAX_MM + 1))
    checar(u"suavização acima do teto é recusada",
           recusa(B.gerar, s, cx, "anatomico", 5, B.SUAVIZACAO_MAX_MM + 1))
    checar(u"modo desconhecido é recusado", recusa(B.gerar, s, cx, "xyz", 5))
    checar(u"direção desconhecida é recusada",
           recusa(B.gerar, s, cx, "anatomico", 5, 0.0, "diagonal"))
    checar(u"caixa sem as seis faces é recusada",
           recusa(B.normalizar_caixa, s, {"x0": 1}))
    checar(u"caixa menor que o mínimo é recusada",
           recusa(B.normalizar_caixa, s, dict(cx, x1=cx["x0"] + 3)))
    ar = caixa_fisica(s, (86.0, -60.0, -30.0), (99.0, -40.0, 30.0))
    checar(u"caixa que não encosta na pele: «não sobrou bólus»",
           u"sobrou" in (recusa(B.gerar, s, ar, "anatomico", 5) or u""))
    teto = B.TETO_POR_GRADE[1.0]
    try:
        B.TETO_POR_GRADE[1.0] = 1000
        m = recusa(B.gerar, s, cx, "anatomico", 5)
    finally:
        B.TETO_POR_GRADE[1.0] = teto
    checar(u"acima do teto de voxels, recusa dizendo o tamanho",
           m and u"grande demais" in m and u"milhões" in m, m)
    n = B.normalizar_caixa(s, dict(cx, x0=-50.0, x1=1e6))
    checar(u"a caixa é aparada para dentro da série",
           n["x0"] == 0.0 and abs(n["x1"] - s.extensao[0]) < 1e-9, n)


def teste_ato():
    secao(u"o ato declarado: a cada exportação, com a frase na letra")
    checar(u"com o ato e a frase, passa",
           B.conferir_ato(True, B.FRASE_DO_ATO))
    checar(u"espaço a mais na frase não reprova",
           B.conferir_ato(True, u"  " + B.FRASE_DO_ATO.replace(u" ", u"  ")))
    for nome, declaro, frase in ((u"sem declarar", False, B.FRASE_DO_ATO),
                                 (u"declarar com 1 em vez de true", 1,
                                  B.FRASE_DO_ATO),
                                 (u"frase trocada", True, u"de acordo"),
                                 (u"sem frase", True, None)):
        try:
            B.conferir_ato(declaro, frase)
            ok = False
        except B.Recusa:
            ok = True
        checar(u"recusa: %s" % nome, ok)
    checar(u"a frase diz rascunho sujeito a revisão física e médica",
           u"rascunho sujeito a revisão física e médica" in B.FRASE_DO_ATO)
    checar(u"o alerta diz as três coisas do pedido",
           u"uso clínico" in B.ALERTA and u"filamento" in B.ALERTA
           and u"dosimetria" in B.ALERTA and u"atenuação" in B.ALERTA)


def teste_face():
    secao(u"o aviso de biometria: pela largura do corpo na caixa")

    class S(object):
        pass

    for largura, esperado in ((150, True), (330, False)):
        s = S()
        m = np.zeros((20, 60, 200), dtype=np.uint8)
        m[:, 10:50, 100 - largura // 4:100 + largura // 4] = 1
        s.previa = {"mask": m, "sp": 2.0}
        cx = {"x0": 0, "x1": 399, "y0": 0, "y1": 119, "z0": 0, "z1": 39}
        checar(u"corpo de %d mm de largura: face=%s" % (largura, esperado),
               B.parece_face(s, cx) == esperado)


def teste_previa_e_corte(series):
    secao(u"a prévia do corpo e o corte com o bólus pintado")
    s = series["HFS"]
    pv = s.previa
    checar(u"a prévia saiu sem a mesa (contorno externo do radai_skin)",
           pv["sem_mesa"])
    q = s.lps_para_quadro(np.array([[0.0, 88.0, 0.0], [0.0, 0.0, 0.0]]))
    ij = np.round(q / pv["sp"]).astype(int)
    m = pv["mask"]
    checar(u"a mesa não está no corpo da prévia",
           m[ij[0, 2], ij[0, 1], ij[0, 0]] == 0)
    checar(u"o centro do corpo está", m[ij[1, 2], ij[1, 1], ij[1, 0]] == 1)
    checar(u"a prévia cabe no teto", m.size <= B.TETO_PREVIA * 1.05, m.size)
    ci = B.caixa_inicial(s)
    ypele = s.lps_para_quadro(np.array([[0.0, -80.0, 0.0]]))[0, 1]
    checar(u"a caixa inicial cruza a pele anterior",
           ci["y0"] < ypele < ci["y1"], (ci, ypele))
    cx = caixa_fisica(s, (-72.0, -104.0, 5.0), (-8.0, -55.0, 55.0))
    res = B.gerar(s, cx, "caixa", 5, 0.0, "ant", marcas=False)
    k = int(round(s.lps_para_quadro(np.array([[0, 0, 30.0]]))[0, 2] / s.esp[2]))
    png = B.corte_png(s, "ax", k, "pele", res)
    checar(u"o corte é PNG", png[:8] == b"\x89PNG\r\n\x1a\n")
    import struct as st
    w, hh = st.unpack(">II", png[16:24])
    checar(u"com o tamanho do corte", (w, hh) == (s.forma[0], s.forma[1]))
    import zlib
    cru = zlib.decompress(png[41:41 + st.unpack(">I", png[33:37])[0]])
    linhas = np.frombuffer(cru, dtype=np.uint8).reshape(hh, 1 + 3 * w)[:, 1:]
    rgb = linhas.reshape(hh, w, 3).astype(int)
    colorido = int(((rgb[:, :, 1] - rgb[:, :, 2]) > 40).sum())
    checar(u"e o bólus pintado por cima (%d pixels)" % colorido, colorido > 50)
    png0 = B.corte_png(s, "ax", k, "pele", None)
    cru0 = zlib.decompress(png0[41:41 + st.unpack(">I", png0[33:37])[0]])
    rgb0 = np.frombuffer(cru0, dtype=np.uint8).reshape(hh, 1 + 3 * w)[:, 1:]
    rgb0 = rgb0.reshape(hh, w, 3).astype(int)
    checar(u"(isca) sem resultado, nada pintado",
           int(((rgb0[:, :, 1] - rgb0[:, :, 2]) > 40).sum()) == 0)

    pb = res["previa"]
    iguais = float(((pb["densidade"] >= 128) == (pb["mask"] > 0)).mean())
    checar(u"a densidade do bólus concorda com a máscara (%.4f)" % iguais,
           iguais >= 0.9999 and pb["densidade"].shape == pb["mask"].shape)
    dm = pv["densidade"]
    checar(u"a do paciente passa da metade no centro do corpo e é zero na mesa",
           dm[ij[1, 2], ij[1, 1], ij[1, 0]] >= 128
           and dm[ij[0, 2], ij[0, 1], ij[0, 0]] == 0)


def teste_a_faixa_tem_a_letra():
    if OFICINA is None:
        secao(u"a faixa da espessura tem a letra do autor")
        _componentes.pulado(u"a letra do autor nos documentos de engenharia")
        return
    OFICINA.teste_a_faixa_tem_a_letra(sys.modules[__name__])


def teste_faixa_da_espessura(series):
    secao(u"a espessura do bólus: 1 a 30 mm, padrão 5 (decisão final, 26/09)")
    s = series["HFS"]
    cx = caixa_fisica(s, (-72.0, -104.0, 5.0), (-8.0, -55.0, 55.0))
    checar(u"as constantes dizem 1, 30 e 5",
           (B.ESPESSURA_MIN_MM, B.ESPESSURA_MAX_MM, B.ESPESSURA_PADRAO_MM)
           == (1, 30, 5),
           (B.ESPESSURA_MIN_MM, B.ESPESSURA_MAX_MM, B.ESPESSURA_PADRAO_MM))
    for n in (0, 31):
        try:
            B.gerar(s, cx, "anatomico", n)
            ok = False
        except B.Recusa as e:
            ok = u"de 1 a 30 mm" in str(e)
        checar(u"%d mm é recusado, dizendo a faixa" % n, ok)
    for n in (1, 30):
        try:
            B.gerar(s, cx, "anatomico", n)
            ok, qual = True, u""
        except B.Recusa as e:
            ok, qual = (u"Espessura fora da faixa" not in str(e)), str(e)
        checar(u"%d mm (a ponta da faixa) não é recusado pela espessura" % n,
               ok, qual)
    import radai_bolus_screen as T
    p = T.pagina()
    m = re.search(r'<input type="number" id="bo-esp"[^>]*>', p)
    checar(u"o campo da tela tem a mesma faixa e o padrão",
           m and u'min="1"' in m.group(0) and u'max="30"' in m.group(0)
           and u'value="5"' in m.group(0), m and m.group(0))


def teste_rente_ao_no(series):
    secao(u"face da caixa exatamente num nó: a volta STL → voxel fecha")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MEDIA, HI_MEDIA)
    r = B.gerar(s, cx, "anatomico", 5, 0.5, "ant", marcas=False)
    lo = ((np.array([cx["x0"], cx["y0"], cx["z0"]]) - np.array(r["off"]))
          / r["grade_mm"])
    checar(u"a face x0 da caixa cai num nó (índice %.4f)" % lo[0],
           abs(lo[0] - round(lo[0])) < 1e-6 and r["grade_mm"] == 1.0, lo)
    checar(u"e a volta é exata (DSC %.5f, colunas ímpares %d)"
           % (r["dsc_ida_volta"], r["colunas_impares"]),
           r["dsc_ida_volta"] >= 0.99999 and r["colunas_impares"] == 0)
    antes = B.RENTE_POR_GRADE
    try:
        B.RENTE_POR_GRADE = 1e-4
        ri = B.gerar(s, cx, "anatomico", 5, 0.5, "ant", marcas=False)
    finally:
        B.RENTE_POR_GRADE = antes
    checar(u"(isca) com o limiar da v8.2 a mesma volta reprova (DSC %.5f)"
           % ri["dsc_ida_volta"], ri["dsc_ida_volta"] < 0.9999)


LO_MOLDE = (-26.0, -100.0, -8.0)
HI_MOLDE = (26.0, -60.0, 12.0)
LADO_LPS = {"superior": (0, 0, 1), "inferior": (0, 0, -1),
            "esquerda": (1, 0, 0), "direita": (-1, 0, 0),
            "externa": (0, -1, 0)}


def _tri_stl(stl):
    return B.ler_stl(stl)[1]


def _distancia_por_bola(pts, tri, ate):
    from scipy.spatial import cKDTree
    t = np.asarray(tri, dtype=np.float64)
    c = t.mean(axis=1)
    raio_tri = float(np.linalg.norm(t - c[:, None, :], axis=2).max())
    arv = cKDTree(c)
    p = np.asarray(pts, dtype=np.float64)
    out = np.full(len(p), np.inf)
    for i, viz in enumerate(arv.query_ball_point(p, ate + raio_tri)):
        if not viz:
            continue
        tt = t[viz]
        q = np.repeat(p[i][None, :], len(tt), 0)
        out[i] = B._ponto_triangulo(q, tt[:, 0], tt[:, 1], tt[:, 2]).min()
    return out


def _sondas(res, t):
    v = _tri_stl(res["stl"]).reshape(-1, 3)
    d = t / 2.0
    y_meio = -82.5
    y_lat = -math.sqrt(80.0 ** 2 - 26.0 ** 2) - 2.5
    return {"superior": [0.0, y_meio, v[:, 2].max() + d],
            "inferior": [0.0, y_meio, v[:, 2].min() - d],
            "esquerda": [v[:, 0].max() + d, y_lat, 2.0],
            "direita": [v[:, 0].min() - d, y_lat, 2.0],
            "externa": [0.0, -85.0 - d, 2.0],
            "pele": [0.0, -80.0 + d, 2.0]}


def _abre_so_do_lado(res, lado, t, tri=None):
    sd = _sondas(res, t)
    tri = _tri_stl(res["molde"]["stl"]) if tri is None else tri
    dentro = dict(zip(sd, B.dentro_da_malha(tri, np.array(list(
        sd.values()))).tolist()))
    certo = all(dentro[k] == (k != lado) for k in dentro)
    return certo, dentro


def _chaves(tri):
    t = np.asarray(tri, dtype=np.float32)
    return set(tuple(sorted(tuple(p) for p in x.tolist())) for x in t)


def teste_molde_aberturas(series):
    secao(u"molde: a abertura está no lado pedido, e só nele")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MOLDE, HI_MOLDE)
    guardado = {}
    for lado in B.ABERTURAS:
        r = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                    molde=True, casca_mm=2, abertura=lado)
        certo, dentro = _abre_so_do_lado(r, lado, 2)
        checar(u"%s: aberto só do lado pedido %s" % (lado, dentro), certo,
               dentro)
        mo = r["molde"]
        esperado = np.array(LADO_LPS[lado], dtype=float)
        checar(u"%s: a normal da abertura, em LPS, aponta para o lado (%.4f)"
               % (lado, float(np.dot(mo["abertura_normal_lps"], esperado))),
               float(np.dot(mo["abertura_normal_lps"], esperado)) >= 0.99
               and mo["abertura_mm2"] >= B.ABERTURA_MIN_MM2,
               (mo["abertura_normal_lps"], mo["abertura_mm2"]))
        guardado[lado] = r
    r = guardado["superior"]
    esp = _tri_stl(r["molde"]["stl"]) * np.array([1.0, 1.0, -1.0])
    c_esp, d_esp = _abre_so_do_lado(r, "superior", 2, esp)
    checar(u"(isca) o molde espelhado em z reprova a mesma pergunta %s"
           % d_esp, not c_esp)
    return guardado


def teste_molde_casca(series, guardado):
    secao(u"molde: a casca tem a espessura pedida, medida na malha")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MOLDE, HI_MOLDE)
    rng = np.random.default_rng(7)

    def medir(r, t):
        tm, tb = _tri_stl(r["molde"]["stl"]), _tri_stl(r["stl"])
        v = np.unique(tm.reshape(-1, 3), axis=0)
        v = v[rng.choice(len(v), min(1500, len(v)), replace=False)]
        d = _distancia_por_bola(v, tb, t + 1.5)
        zc = tb.reshape(-1, 3)[:, 2].max()
        fora = (d > t / 2.0) & (np.abs(v[:, 2] - zc) > 1e-3)
        d = d[fora]
        return {"n": int(d.size), "mediana": float(np.median(d)),
                "p01": float(np.percentile(d, 1)),
                "p99": float(np.percentile(d, 99))}

    def dentro_da_tolerancia(m, t):
        return (abs(m["mediana"] - t) <= 0.05 and m["p01"] >= t - 0.15
                and m["p99"] <= t + 0.15 and m["n"] >= 300)

    for t in (2, 4):
        r = (guardado["superior"] if t == 2 else
             B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                     molde=True, casca_mm=t, abertura="superior"))
        m = medir(r, t)
        mo = r["molde"]["espessura"]
        print(u"         · casca %d mm (grade %.2f): força bruta mediana %.3f "
              u"p01 %.3f p99 %.3f (%d vértices); motor mediana %.3f"
              % (t, r["grade_mm"], m["mediana"], m["p01"], m["p99"], m["n"],
                 mo["mediana"]))
        checar(u"casca de %d mm: mediana, 1º e 99º percentis perto dela" % t,
               dentro_da_tolerancia(m, t), m)
        checar(u"casca de %d mm: a medida do motor concorda com a da bateria"
               % t, abs(mo["mediana"] - m["mediana"]) <= 0.02
               and abs(mo["p01"] - m["p01"]) <= 0.05, (mo, m))
        checar(u"(isca) a mesma medida contra %d mm reprova" % (t + 1),
               not dentro_da_tolerancia(m, t + 1))
    cap = {}
    molde, dist = B._molde, B._distancia_exata

    def espia(Fp, *a):
        cap["Fp"] = Fp
        return molde(Fp, *a)

    def aos_voxels(pontos, tri, arvore, k=None, bloco=None):
        from scipy.spatial import cKDTree
        zz, yy, xx = np.nonzero(cap["Fp"] < 0)
        c = np.stack([xx, yy, zz], 1).astype(float) - 1.0
        return cKDTree(c).query(pontos)[0]

    try:
        B._molde, B._distancia_exata = espia, aos_voxels
        ri = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                     molde=True, casca_mm=2, abertura="superior")
    finally:
        B._molde, B._distancia_exata = molde, dist
    mi = medir(ri, 2)
    checar(u"(isca) com a distância aos centros de voxel, a casca de 2 mm "
           u"reprova (mediana %.3f)" % mi["mediana"],
           not dentro_da_tolerancia(mi, 2), mi)


def teste_molde_interior(series, guardado):
    secao(u"molde: o interior é o bólus, triângulo a triângulo")
    r = guardado["superior"]
    mo = r["molde"]
    tb, tm = _tri_stl(r["stl"]), _tri_stl(mo["stl"])
    kb, km = _chaves(tb), _chaves(tm)
    comuns = kb & km
    it = mo["interior"]
    checar(u"os vértices da face interna SÃO vértices do bólus (%d de %d)"
           % (it["vertices_iguais"], it["vertices_internos"]),
           it["vertices_internos"] > 1000
           and it["vertices_iguais"] == it["vertices_internos"], it)
    checar(u"no STL, %d triângulos do bólus estão no molde — o que o motor "
           u"contou (%d)" % (len(comuns), it["no_molde"]),
           len(comuns) == it["no_molde"] and len(comuns) > 0.8 * len(kb))
    nb = {tuple(sorted(tuple(p) for p in x.tolist())):
          np.cross(x[1] - x[0], x[2] - x[0])
          for x in np.asarray(tb, dtype=np.float64)}
    opostas = 0
    for x in np.asarray(tm, dtype=np.float64):
        k = tuple(sorted(tuple(p) for p in np.float32(x).tolist()))
        if k in comuns:
            opostas += float(np.dot(np.cross(x[1] - x[0], x[2] - x[0]),
                                    nb[k])) < 0
    checar(u"e todos com a normal invertida (%d de %d)" % (opostas, len(comuns)),
           opostas == len(comuns))

    def fora_da_abertura(tri_b, comuns_):
        zc = tri_b.reshape(-1, 3)[:, 2].max()
        h = r["grade_mm"]
        n = 0
        for x in np.asarray(tri_b, dtype=np.float32):
            k = tuple(sorted(tuple(p) for p in x.tolist()))
            if k not in comuns_ and abs(float(x[:, 2].mean()) - zc) > 2 * h:
                n += 1
        return n

    fora = fora_da_abertura(tb, comuns)
    checar(u"o único pedaço do bólus que o molde não repete é a abertura "
           u"(%d triângulos fora dela)" % fora, fora == 0)

    def vertices_desviados(r_):
        tb_, tm_ = _tri_stl(r_["stl"]), _tri_stl(r_["molde"]["stl"])
        vb = set(map(tuple, np.float32(tb_.reshape(-1, 3)).tolist()))
        vm = np.unique(tm_.reshape(-1, 3), axis=0)
        zc = tb_.reshape(-1, 3)[:, 2].max()
        cand = np.array([p for p in vm if tuple(np.float32(p).tolist()) not in vb
                         and abs(p[2] - zc) > 1e-3])
        if not len(cand):
            return 0
        t = r_["molde"]["casca_mm"]
        return int((_distancia_por_bola(cand, tb_, t / 2.0) < t / 2.0).sum())

    dv = vertices_desviados(r)
    checar(u"todo vértice do molde junto ao bólus É um vértice do bólus "
           u"(%d desviados)" % dv, dv == 0)
    sup = B.superficie

    def sem_posicao(F, celulas_por_fatia=None, posicao=None, com_chaves=False):
        out = sup(F, celulas_por_fatia, com_chaves=com_chaves)
        if posicao is None:
            return out
        v, f = out[0], out[1]
        return tuple([v, f, np.ones(len(v), dtype=np.int8)]
                     + ([out[2]] if com_chaves else []))

    s = series["HFS"]
    cx = caixa_fisica(s, LO_MOLDE, HI_MOLDE)
    try:
        B.superficie = sem_posicao
        ri = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                     molde=True, casca_mm=2, abertura="superior")
    finally:
        B.superficie = sup
    di = vertices_desviados(ri)
    checar(u"(isca) com a interpolação do máximo, a mesma pergunta reprova "
           u"(%d vértices desviados)" % di, di > 0)


def teste_molde_fechado(series, guardado):
    secao(u"molde: a malha fechada é um sólido — a borda da abertura fecha")
    for lado, r in sorted(guardado.items()):
        mo = r["molde"]
        tm = _tri_stl(mo["stl"])
        u_, inv = np.unique(tm.reshape(-1, 3), axis=0, return_inverse=True)
        cm = B.conferir_malha(u_, np.asarray(inv).reshape(-1, 3))
        checar(u"%s: relido do STL, fechado e para fora (%d triângulos)"
               % (lado, cm["triangulos"]), cm["fechada"]
               and cm["volume_mm3"] > 0, cm)
        checar(u"%s: volta STL → voxel exata e uma peça só (DSC %.5f)"
               % (lado, mo["dsc_ida_volta"]),
               mo["dsc_ida_volta"] >= 0.99999 and mo["colunas_impares"] == 0
               and mo["pecas"] == 1 and mo["exportavel"], mo["pecas"])
        checar(u"%s: o cabeçalho é o do molde, rascunho, e nada da série"
               % lado, mo["stl"][:80] == B.CABECALHO_STL_MOLDE.ljust(80, b" ")
               and B.cabecalho_seguro(mo["stl"][:80])
               and b"ZZSENTINELA" not in mo["stl"])
    checar(u"o cabeçalho do molde cabe nos 80 bytes sem ser cortado (%d)"
           % len(B.CABECALHO_STL_MOLDE), len(B.CABECALHO_STL_MOLDE) <= 80)
    r = guardado["superior"]
    tm = _tri_stl(r["molde"]["stl"])
    zc = _tri_stl(r["stl"]).reshape(-1, 3)[:, 2].max()
    na_borda = (np.abs(tm[:, :, 2] - zc) < 1e-3).all(axis=1)
    sem = tm[~na_borda]
    u_, inv = np.unique(sem.reshape(-1, 3), axis=0, return_inverse=True)
    cm = B.conferir_malha(u_, np.asarray(inv).reshape(-1, 3))
    checar(u"(isca) sem os %d triângulos da borda, a malha abre (%d arestas "
           u"sem par)" % (int(na_borda.sum()), cm["arestas_sem_par"]),
           na_borda.sum() > 0 and not cm["fechada"])


def teste_molde_no_corte(series, guardado):
    secao(u"molde: o corte da tela pinta o molde, na cor da cera")
    import struct as st
    import zlib
    s = series["HFS"]
    r = guardado["superior"]
    k = int(round(s.lps_para_quadro(np.array([[0, 0, 2.0]]))[0, 2] / s.esp[2]))

    def ambar(res):
        png = B.corte_png(s, "ax", k, "pele", res)
        w, hh = st.unpack(">II", png[16:24])
        cru = zlib.decompress(png[41:41 + st.unpack(">I", png[33:37])[0]])
        rgb = np.frombuffer(cru, dtype=np.uint8).reshape(hh, 1 + 3 * w)[:, 1:]
        rgb = rgb.reshape(hh, w, 3).astype(int)
        return int(((rgb[:, :, 0] - rgb[:, :, 2] > 80)
                    & (rgb[:, :, 0] > rgb[:, :, 1] + 15)).sum())

    n = ambar(r)
    checar(u"o corte axial pelo meio da caixa mostra o molde (%d pixels)" % n,
           n > 30)
    checar(u"(isca) o mesmo corte sem o molde não tem âmbar",
           ambar(dict(r, molde=None)) == 0)


def teste_molde_grade(series):
    secao(u"molde: a casca de 1 mm só na grade de 0,5 mm (senão a parede fura)")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MOLDE, HI_MOLDE)
    try:
        B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False, molde=True,
                casca_mm=1, abertura="superior")
        msg = u""
    except B.Recusa as e:
        msg = str(e)
    checar(u"casca de 1 mm numa caixa que não cabe a 0,5 mm: recusada, "
           u"dizendo a casca", u"Casca de 1 mm" in msg and u"0.58" in msg,
           msg)
    peq = caixa_fisica(s, (-28.0, -98.0, -10.0), (-8.0, -68.0, 10.0))
    r = B.gerar(s, peq, "anatomico", 5, 0.0, "ant", marcas=False, molde=True,
                casca_mm=1, abertura="direita")
    mo = r["molde"]
    checar(u"numa caixa pequena ela sai, na grade de 0,5 mm, fechada",
           r["grade_mm"] == 0.5 and mo["malha"]["fechada"]
           and mo["dsc_ida_volta"] >= 0.99999, (r["grade_mm"], mo["malha"]))
    checar(u"e com 1 mm medido (mediana %.3f)" % mo["espessura"]["mediana"],
           abs(mo["espessura"]["mediana"] - 1.0) <= 0.05
           and mo["espessura"]["p01"] >= 0.85)
    antes = B._CASCA_POR_GRADE
    try:
        B._CASCA_POR_GRADE = 0.0
        ri = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                     molde=True, casca_mm=1, abertura="superior")
    finally:
        B._CASCA_POR_GRADE = antes
    certo, dentro = _abre_so_do_lado(ri, "superior", 1)
    checar(u"(isca) sem a regra, a casca de 1 mm a %.2f mm fura %s — com a "
           u"malha «fechada» (%s)" % (ri["grade_mm"], dentro,
                                      ri["molde"]["malha"]["fechada"]),
           not certo)


def teste_molde_fragmento(series):
    secao(u"molde: fragmento solto da casca sai (impresso, ele cairia)")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MEDIA, HI_MEDIA)
    r = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False, molde=True,
                casca_mm=3, abertura="externa")
    mo = r["molde"]
    checar(u"a abertura externa soltou um fragmento ao lado da saliência "
           u"(%.0f mm³), e ele saiu: uma peça" % mo["fragmentos_mm3"],
           mo["fragmentos_mm3"] > 0 and mo["pecas"] == 1
           and any(u"fragmentos" in a for a in mo["avisos"]), mo["avisos"])
    antes = B.FRAGMENTO_MAX_FRACAO
    try:
        B.FRAGMENTO_MAX_FRACAO = 0.0
        ri = B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                     molde=True, casca_mm=3, abertura="externa")
    finally:
        B.FRAGMENTO_MAX_FRACAO = antes
    checar(u"(isca) sem tirar o fragmento, o molde tem %d peças"
           % ri["molde"]["pecas"], ri["molde"]["pecas"] > 1)


def teste_molde_recusas_e_nome(series):
    secao(u"molde: o que ele recusa, e o nome do arquivo")
    s = series["HFS"]
    cx = caixa_fisica(s, LO_MOLDE, HI_MOLDE)
    checar(u"casca de 1 a 4 mm, padrão 2; cinco aberturas, padrão superior",
           (B.CASCA_MIN_MM, B.CASCA_MAX_MM, B.CASCA_PADRAO_MM) == (1, 4, 2)
           and B.ABERTURAS == ("externa", "superior", "inferior", "esquerda",
                               "direita") and B.ABERTURA_PADRAO == "superior")
    for nome, casca, ab in ((u"casca 0", 0, "superior"),
                            (u"casca 5", 5, "superior"),
                            (u"casca quebrada", 2.5, "superior"),
                            (u"abertura desconhecida", 2, "diagonal")):
        try:
            B.gerar(s, cx, "anatomico", 5, 0.0, "ant", marcas=False,
                    molde=True, casca_mm=casca, abertura=ab)
            ok = False
        except B.Recusa:
            ok = True
        checar(u"recusa: %s" % nome, ok)
    grande = caixa_fisica(s, (-95.0, -99.0, -72.0), (95.0, 90.0, 72.0))
    t0 = time.time()
    try:
        B.gerar(s, grande, "caixa", None, 1.0, "ant", marcas=True, molde=True,
                casca_mm=2, abertura="superior")
        msg = u""
    except B.Recusa as e:
        msg = str(e)
    checar(u"acima do teto do molde (%d M voxels), recusa dizendo o tamanho, "
           u"em %.1f s" % (B.TETO_MOLDE_VOXELS // 1000000, time.time() - t0),
           u"grande demais para o molde" in msg and u"milhões" in msg
           and time.time() - t0 < 5.0, msg)
    res = {"modo": "anatomico", "espessura_mm": 5,
           "molde": {"casca_mm": 2, "abertura": "superior"}}
    n = B.nome_do_molde(res, u"0123456789abcdef")
    checar(u"o nome do molde (%s)" % n, n ==
           u"RadAI_bolus_DRAFT_anatomical_5mm_MOLD_wall2mm_open-superior_"
           u"01234567.stl")
    res2 = dict(res, molde={"casca_mm": 3, "abertura": "externa"})
    n2 = B.nome_do_molde(res2, u"../BELTRANO^ISCA 1.2.840/xy")
    checar(u"(isca) sorteio com texto estranho não passa para o nome (%s)"
           % n2, u"BELTRANO" not in n2 and u"/" not in n2
           and u"open-external" in n2)
    checar(u"o molde casa com o bólus pelo fim do nome (o mesmo sorteio)",
           B.nome_do_stl(res, u"0123456789abcdef")[-12:] == n[-12:])


def _rota_chama_antes(fonte, rota, chamada, antes_de="Response"):
    arv = ast.parse(fonte)
    for no in ast.walk(arv):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        dec = [d for d in no.decorator_list if isinstance(d, ast.Call)
               and d.args and isinstance(d.args[0], ast.Constant)
               and d.args[0].value == rota]
        if not dec:
            continue
        chama, monta = [], []
        for sub in ast.walk(no):
            if isinstance(sub, ast.Call):
                f = sub.func
                nome = f.attr if isinstance(f, ast.Attribute) else getattr(
                    f, "id", "")
                if nome == chamada:
                    chama.append(sub.lineno)
                if nome == antes_de:
                    monta.append(sub.lineno)
        return bool(chama) and bool(monta) and min(chama) < min(monta)
    return False


def _gets_com_caminho(fonte):
    arv = ast.parse(fonte)
    ruins = []
    for no in ast.walk(arv):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in no.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "get"):
                for a in no.args.args:
                    if a.arg in ("pasta", "caminho", "path", "dir", "arquivo"):
                        ruins.append((no.name, a.arg))
    return ruins


def teste_o_popup_da_serie():
    secao(u"a série no popup da casca: «Aponte uma pasta» é a padrão, o acervo continua")
    import radai_bolus_screen as T
    p = T.pagina()
    checar(u"o cartão «Escolha a série» abre o popup, que abre sozinho",
           u'id="bo-cartao" data-ui-ps-abre="bo_escolha"' in p
           and u'<div class="ui-ps" id="bo_escolha" data-ui-ps' in p
           and u"data-sozinho>" in p.split(u'id="bo_escolha"')[1][:160])
    checar(u"  as abas: o acervo primeiro, a pasta como padrão (a segunda)",
           u'class="ui-guias esq" id="bo_origem" data-ativa="pasta"' in p
           and 0 <= p.find(u'data-guia="acervo"') < p.find(u'data-guia="pasta"')
           and u'id="bo_acervo" data-ui-acervo' in p)
    checar(u"  e o campo da pasta, a lista e o Abrir moram no popup",
           all(p.find(u'id="%s"' % i) > p.find(u'id="bo_escolha"')
               for i in (u"bo-pasta", u"bo-serie", u"bo-abrir", u"bo-msg-ps")))
    js = T.JS
    checar(u"o acervo pede por POST, com o bilhete, e abre pelo mesmo caminho do Abrir",
           u"post('/api/bolus/acervo', {bilhete: linha.bilhete})" in js
           and u"boAbrir(d.b)" in js and u"/api/bolus/acervo?" not in js)
    lidos = {}
    vistos = []

    def resolver(b):
        vistos.append(b)
        return {u"B1": (u"C:\\fantoma\\CT", u"1.2.3.4"),
                u"B2": (u"C:\\fantoma\\MR", u"1.2.3.5")}.get(b, (None, None))

    def detalhes(bs):
        return [{u"modalidade": u"CT" if bs[0] == u"B1" else u"MR", u"cortes": 120,
                 u"espessura_mm": 2.0}]
    d = T.serie_do_acervo(u"B1", resolver, detalhes)
    lidos = T._L.get(u"B1") or {}
    checar(u"a série do acervo entra na lista do bólus pelo bilhete dela, sem caminho na resposta",
           d.get(u"b") == u"B1" and not d.get(u"recusada")
           and u"fantoma" not in json.dumps(d) and lidos.get(u"uid") == u"1.2.3.4"
           and lidos.get(u"modalidade") == u"CT", d)
    d2 = T.serie_do_acervo(u"B2", resolver, detalhes)
    checar(u"  RM do acervo vem recusada, com o motivo", bool(d2.get(u"recusada")), d2)
    d3 = T.serie_do_acervo(u"ZZ", resolver, detalhes)
    checar(u"  e bilhete fora do acervo diz que a série saiu, sem abrir nada",
           d3 == {u"erro": T.SERIE_FORA_DO_ACERVO} and u"ZZ" not in T._L, d3)
    for b in (u"B1", u"B2"):
        T._L.pop(b, None)


def teste_tela():
    secao(u"a tela: o alerta à vista, o ato desmarcado, e nada de caminho em GET")
    import radai_bolus_screen as T
    p = T.pagina()
    checar(u"a página tem corpo", len(p) > 20000, len(p))
    checar(u"nenhum marcador @X@ sobrou", not re.findall(r"@[A-Z0-9_]+@", p),
           re.findall(r"@[A-Z0-9_]+@", p))
    checar(u"o alerta do autor está na tela, fora de balão",
           B.ALERTA in p and B.ALERTA not in u"".join(
               re.findall(r"ui-balao.*?</span>", p, re.S)))
    checar(u"a frase do ato está na janela de exportação",
           B.FRASE_DO_ATO in p)
    m = re.search(r'<input type="checkbox" id="bo-ato"[^>]*>', p)
    checar(u"a caixa do ato NASCE desmarcada",
           m and u"checked" not in m.group(0), m and m.group(0))
    m2 = re.search(r'<button[^>]*id="bo-exp-ok"[^>]*>', p)
    checar(u"e o botão de exportar nasce desligado",
           m2 and u"disabled" in m2.group(0))
    checar(u"a janela zera a caixa a cada abertura",
           u"el('bo-ato').checked = false" in T.JS)
    checar(u"a frase vai ao servidor pela constante, não pelo DOM",
           u"var FRASE = " + json.dumps(B.FRASE_DO_ATO) in p)
    checar(u"o JS não põe pasta em URL",
           u"pasta=" not in T.JS and u"?pasta" not in T.JS)
    checar(u"sem WebGL", u"webgl" not in p.lower())
    checar(u"sem biblioteca de fora", u"<script src" not in p.lower())
    fonte = io.open(_componentes.fonte("app/radai_bolus_screen.py"),
                    encoding="utf-8").read()
    checar(u"a rota do STL confere o ato ANTES de montar a resposta",
           _rota_chama_antes(fonte, "/api/bolus/stl", "conferir_ato"))
    isca = fonte.replace(u"radai_bolus.conferir_ato(c.get(\"declaro\"), "
                         u"c.get(\"frase\"))", u"pass")
    checar(u"(isca) sem a chamada, a checagem reprova",
           isca != fonte and not _rota_chama_antes(isca, "/api/bolus/stl",
                                                   "conferir_ato"))
    checar(u"nenhuma rota GET aceita caminho", not _gets_com_caminho(fonte),
           _gets_com_caminho(fonte))
    isca2 = (u"@app.get('/x')\ndef f(pasta: str = ''):\n    pass\n")
    checar(u"(isca) um GET com `pasta` seria acusado",
           bool(_gets_com_caminho(isca2)))
    checar(u"o renderizador portado do DeFace está lá (a rampa fria)",
           u"function frio(" in T.JS and u"73 + q2*163" in T.JS)
    checar(u"e o bólus é translúcido sobre o paciente",
           u"rampaB = cena.rampaB || lima" in T.JS
           and u"rampaP = cena.rampaP || frio" in T.JS
           and u"alfa = cena.alfa || 0.62" in T.JS
           and u"var bc = rampaB(" in T.JS)
    m = re.search(r'<input type="checkbox" id="bo-molde"[^>]*>', p)
    checar(u"a caixa do molde existe e NASCE desmarcada",
           m and u"checked" not in m.group(0), m and m.group(0))
    m = re.search(r'<input type="number" id="bo-casca"[^>]*>', p)
    checar(u"o campo da casca tem a faixa e o padrão do módulo",
           m and (u'min="%d"' % B.CASCA_MIN_MM) in m.group(0)
           and (u'max="%d"' % B.CASCA_MAX_MM) in m.group(0)
           and (u'value="%d"' % B.CASCA_PADRAO_MM) in m.group(0),
           m and m.group(0))
    ops = re.findall(r'<option value="([a-z]+)"( selected)?',
                     p[p.index(u'id="bo-abertura"'):p.index(u"</select>",
                       p.index(u'id="bo-abertura"'))])
    checar(u"as cinco aberturas, na ordem do módulo, com o padrão marcado",
           [o[0] for o in ops] == list(B.ABERTURAS)
           and [o[0] for o in ops if o[1]] == [B.ABERTURA_PADRAO], ops)
    m = re.search(r'<button id="bo-exportar-molde"[^>]*>', p)
    checar(u"o botão do STL do molde nasce desligado e à vista",
           m and u"disabled" in m.group(0) and u"hidden" not in m.group(0))
    checar(u"a tela manda a casca e a abertura SÓ com o molde marcado",
           u"if(p.molde){ p.casca = +el('bo-casca').value; "
           u"p.abertura = el('bo-abertura').value }" in T.JS)
    checar(u"e a exportação diz qual peça (o mesmo ato, a mesma rota)",
           u"frase: FRASE, peca: BO.peca" in T.JS)
    checar(u"o servidor só liga o molde com `molde: true` (e não com "
           u"«false» em texto)", u'molde=c.get("molde") is True' in fonte)
    T._S.update({"b": "x", "serie": object(), "visto": 1000.0})
    falta = T._soltar_se_parada(agora=1000.0 + 60, rearmar=False)
    checar(u"a série fica enquanto alguém olha", falta and falta > 0)
    T._soltar_se_parada(agora=1000.0 + T.SOLTAR_APOS_S + 1, rearmar=False)
    checar(u"e sai da memória depois de %d min parada"
           % (T.SOLTAR_APOS_S // 60), T._S["serie"] is None)


_CAMPOS_ROTULADOS = ("bo-esp", "bo-suav", "bo-dir", "bo-casca", "bo-abertura")


def _sem_nome(p):
    fora = [i for i in _CAMPOS_ROTULADOS
            if not re.search(r'<label[^>]*\bfor="%s"' % i, p)]
    for cv in ("bo-c3d", "bo-c3b"):
        m = re.search(r'<canvas id="%s"[^>]*>' % cv, p)
        if not (m and u'role="img"' in m.group(0)
                and re.search(r'aria-label="[^"]{8,}"', m.group(0))):
            fora.append(cv)
    return fora


def teste_nomes_acessiveis():
    secao(u"a tela: todo campo com rótulo de verdade, e o 3D com nome")
    import radai_bolus_screen as T
    p = T.pagina()
    faltam = _sem_nome(p)
    checar(u"os cinco campos têm `<label for>` e os dois canvas têm nome",
           not faltam, faltam)
    isca = p.replace(u'<label class="g-rot" for="bo-casca" data-radai-frase>'
                     u'Casca do molde (mm)</label>',
                     u'<span data-radai-frase>Casca do molde (mm)</span>')
    checar(u"  (isca) a Casca com o rótulo num `<span>` é acusada",
           isca != p and u"bo-casca" in _sem_nome(isca), _sem_nome(isca))
    bts = re.findall(r'<button type="button" class="bo-bt2[^"]*" data-ver="[a-z]+"'
                     r'[^>]*>', p)
    checar(u"os três botões de vista dizem o estado (`aria-pressed`)",
           len(bts) == 3 and all(u"aria-pressed=" in b for b in bts), bts)
    checar(u"  e o clique o acerta junto com a classe",
           u"x.setAttribute('aria-pressed', x === bt ? 'true' : 'false')"
           in T.JS)
    checar(u"  e o rótulo novo tem a mesma folha do antigo",
           u".bo-ctl .g > label.g-rot" in T.CSS)


def _funcoes_js(js, nomes):
    partes = []
    for n in nomes:
        i = js.index(u"function %s(" % n)
        j = js.index(u"{", i)
        prof = 0
        for k in range(j, len(js)):
            if js[k] == u"{":
                prof += 1
            elif js[k] == u"}":
                prof -= 1
                if prof == 0:
                    partes.append(js[i:k + 1])
                    break
    return u"\n".join(partes)


_HARNESS_JS = u"""
var n = 41, sp = 1.5, off = [-30, -30, -30], d = new Uint8Array(n*n*n);
for(var z = 0; z < n; z++) for(var y = 0; y < n; y++) for(var x = 0; x < n; x++){
  var X = off[0] + x*sp, Y = off[1] + y*sp, Z = off[2] + z*sp;
  var F = Math.hypot(X, Y, Z) - 20;               // a esfera de raio 20 mm
  d[(z*n + y)*n + x] = Math.max(0, Math.min(255, Math.round(128 - F*64)));
}
var v = {nx: n, ny: n, nz: n, sp: sp, off: off, d: d};
function acerto(cam, u, w){
  var o = [cam.right[0]*u + cam.up[0]*w - cam.dir[0]*100,
           cam.right[1]*u + cam.up[1]*w - cam.dir[1]*100,
           cam.right[2]*u + cam.up[2]*w - cam.dir[2]*100];
  var passo = sp*0.85, t = 0;
  for(; t < 200; t += passo){
    if(amostra(v, o[0] + cam.dir[0]*t, o[1] + cam.dir[1]*t, o[2] + cam.dir[2]*t)) break;
  }
  t = refinar(v, o, cam.dir, t, passo);
  var P = [o[0] + cam.dir[0]*t, o[1] + cam.dir[1]*t, o[2] + cam.dir[2]*t];
  return {P: P, n: normalVol(v, P, cam)};
}
var out = {};
[['frente', 0], ['direita', 90], ['tras', 180], ['esquerda', -90]].forEach(function(q){
  var c = camera({yaw: q[1], pitch: 0});
  out[q[0]] = {right: c.right, up: c.up, dir: c.dir, centro: acerto(c, 0, 0),
               lado: acerto(c, 10, 0)};
});
out.laje = laje([0, -100, 0], [0, 1, 0], [-5, -5, -5, 5, 5, 5]);
out.laje_fora = laje([50, -100, 0], [0, 1, 0], [-5, -5, -5, 5, 5, 5]);
console.log(JSON.stringify(out));
"""


def teste_js_do_3d():
    secao(u"o 3D do navegador: a matemática do raio, rodada no node")
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print(u"         · node ausente: a matemática do JS NÃO foi medida")
        return
    import radai_bolus_screen as T
    fn = _funcoes_js(T.JS, ["cruz", "norma", "tri255", "tri", "refinar",
                            "amostra", "normalVol", "camera", "laje"])
    arq = os.path.join(_cleanup.temporaria("radai_teste_bolusjs_"), "t.js")
    io.open(arq, "w", encoding="utf-8").write(fn + _HARNESS_JS)
    p = subprocess.run([node, arq], capture_output=True, text=True,
                       timeout=60)
    checar(u"as funções do raio rodam fora do navegador", p.returncode == 0,
           (p.stderr or u"")[:200])
    if p.returncode != 0:
        return
    o = json.loads(p.stdout)
    f = o["frente"]
    checar(u"de frente, a direita da tela é a ESQUERDA do paciente (+x)",
           np.allclose(f["right"], [1, 0, 0]) and np.allclose(f["up"], [0, 0, 1])
           and np.allclose(f["dir"], [0, 1, 0]), f)
    for nome in ("frente", "direita", "tras", "esquerda"):
        c = o[nome]
        checar(u"%s: a tela é destra (direita × cima = −dir)" % nome,
               np.allclose(np.cross(c["right"], c["up"]),
                           -np.array(c["dir"]), atol=1e-9))
        P = np.array(c["centro"]["P"])
        checar(u"%s: o raio do centro acerta a esfera a 20 mm (%.3f)"
               % (nome, np.linalg.norm(P)), abs(np.linalg.norm(P) - 20) < 0.25)
        nn = c["centro"]["n"]
        checar(u"%s: e a normal olha para quem olha (z = %.3f)" % (nome, nn[2]),
               nn[2] > 0.98)
        L = np.array(c["lado"]["P"])
        esperado = np.array(c["right"]) * 10
        checar(u"%s: o raio 10 mm à direita da tela acerta onde a câmera diz"
               % nome, abs(np.dot(L, np.array(c["right"])) - 10) < 1e-6
               and np.linalg.norm(np.cross(L - esperado,
                                           np.array(c["dir"]))) < 1e-6)
    d = o["direita"]
    checar(u"vista «Direita»: olha a partir da direita do paciente (dir = +x) "
           u"com a frente dele à direita da tela",
           np.allclose(d["dir"], [1, 0, 0]) and np.allclose(d["right"],
                                                            [0, -1, 0]), d)
    checar(u"a laje acerta a caixa na entrada e na saída",
           o["laje"] and abs(o["laje"][0] - 95) < 1e-9
           and abs(o["laje"][1] - 105) < 1e-9, o["laje"])
    checar(u"(isca) e o raio que passa ao lado não acerta", o["laje_fora"] is None)
    isca = np.cross(-np.array(f["right"]), f["up"])
    checar(u"(isca) uma tela espelhada (direita trocada) reprova a conta",
           not np.allclose(isca, -np.array(f["dir"])))


def _escrever_dicom(pasta, modalidade="CT", n=52, nome="ZZSENTINELA^ISCA^RM"):
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    os.makedirs(pasta, exist_ok=True)
    lado, px, esp = 170, 1.2, 3.0
    serie, estudo, fr = generate_uid(), generate_uid(), generate_uid()
    x0 = -(lado - 1) * px / 2.0
    for k in range(n):
        z = -75.0 + k * esp
        jj, ii = np.meshgrid(np.arange(lado), np.arange(lado), indexing="ij")
        p = np.stack([x0 + ii.ravel() * px, x0 + jj.ravel() * px,
                      np.full(ii.size, z)], 1)
        arr = hu_fisico(p).reshape(lado, lado).astype(np.int16)
        meta = Dataset()
        meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        meta.MediaStorageSOPInstanceUID = generate_uid()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(None, {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID = meta.MediaStorageSOPClassUID
        ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
        ds.Modality = modalidade
        ds.PatientName = nome
        ds.PatientID = "ZZ0001"
        ds.StudyInstanceUID, ds.SeriesInstanceUID = estudo, serie
        ds.FrameOfReferenceUID = fr
        ds.SeriesNumber, ds.InstanceNumber = 3, k + 1
        ds.SeriesDate = "20260901"
        ds.ImagePositionPatient = [x0, x0, z]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PatientPosition = "HFS"
        ds.SliceThickness = esp
        ds.PixelSpacing = [px, px]
        ds.Rows = ds.Columns = lado
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.BitsAllocated = ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.RescaleIntercept, ds.RescaleSlope = 0, 1
        ds.PixelData = arr.tobytes()
        ds.save_as(os.path.join(pasta, "IM%04d.dcm" % k),
                   enforce_file_format=True)


def teste_rotas():
    secao(u"as rotas: bilhete, RM recusada, e o STL só com o ato")
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as e:
        checar(u"fastapi.testclient disponível", False, e)
        return
    import radai_bolus_screen as T
    base = _cleanup.temporaria("radai_teste_bolus_")
    _escrever_dicom(os.path.join(base, "PAC", "CT"), "CT", 52,
                    "ZZSENTINELA^ISCA^TC")
    _escrever_dicom(os.path.join(base, "PAC", "RM"), "MR", 24,
                    "ZZSENTINELA^ISCA^RM")
    app = FastAPI()
    ouvidos = []
    T.montar(app, ouvidos.append)
    cli = TestClient(app)
    checar(u"o arquivo dos atos mora no acervo ISOLADO da bateria",
           os.path.dirname(T.arquivo_de_atos())
           == os.environ.get("RADAI_CALIB_DIR"), T.arquivo_de_atos())
    import radai_varrer
    radai_varrer.montar(app)
    rotas = set(getattr(x, "path", u"") for x in app.routes)
    checar(u"a aba «Aponte uma pasta» não tem mais POST único próprio",
           u"/api/bolus/series" not in rotas and u"/api/varrer/iniciar" in rotas,
           sorted(x for x in rotas if u"series" in x or u"varrer" in x))
    _escrever_dicom(os.path.join(base, "PAC", "LOCALIZADOR"), "CT", 6,
                    "ZZSENTINELA^ISCA^LOC")
    d = cli.post("/api/varrer/iniciar", json={
        "uso": T.USO_DA_VARREDURA, "pasta": base, "dias": 0}).json()
    prazo = time.time() + 60.0
    while not d.get("fim") and time.time() < prazo:
        time.sleep(0.1)
        d = cli.post("/api/varrer/estado", json={"v": d.get("v")}).json()
    r = {"series": d.get("linhas") or []}
    series = r["series"]
    checar(u"a pasta lista as duas séries pela varredura da casca, e o "
           u"localizador de 6 cortes fica de fora (mínimo de %d)" % T.MIN_CORTES,
           len(series) == 2 and d.get("fim") and not d.get("erro"), d)
    crua = {"bilhete": u"B", "uid": u"1.2.3", "pid": u"ZZ0001",
            "descricao": u"ZZSENTINELA", "modalidade": u"CT", "date": u"20240101"}
    T.linha_do_bolus(crua, u"C:\\fantoma", {"uid": u"1.2.3", "cortes": 40,
                                            "numero": 3})
    checar(u"  a linha que vai à tela leva só o bilhete, o rótulo e a recusa",
           set(crua) == {u"bilhete", u"b", u"rotulo", u"recusada"}
           and u"ZZ" not in json.dumps(crua), crua)
    radai_varrer.registrar_series_de_pasta(u"teste_bolus_cru")
    dc = radai_varrer.iniciar(u"teste_bolus_cru", base, dias=0,
                              em_segundo_plano=False)
    cru = radai_varrer.estado(dc.get("v")).get("linhas") or []
    checar(u"  (isca) sem o enriquecer do bólus, a linha da varredura levaria "
           u"o ID do paciente", u"ZZ0001" in json.dumps(cru))
    T._L.pop(u"B", None)
    tc = [x for x in series if not x["recusada"]]
    rm = [x for x in series if x["recusada"]]
    checar(u"a RM vem RECUSADA, com o motivo, e não some",
           len(rm) == 1 and u"RM" in rm[0]["recusada"], rm)
    corpo = json.dumps(r)
    checar(u"nem a pasta nem o nome saem na lista",
           base not in corpo and u"ZZSENTINELA" not in corpo
           and u"ZZ0001" not in corpo)
    if not tc:
        return
    b = tc[0]["b"]
    checar(u"o bilhete é opaco (32 hex)", re.match(r"^[0-9a-f]{32}$", b))
    checar(u"o número da série sai inteiro no rótulo («série 3»)",
           u"série 3 ·" in tc[0]["rotulo"], tc[0]["rotulo"])
    e = cli.post("/api/bolus/abrir", json={"b": rm[0]["b"]}).json()
    checar(u"abrir a RM é recusado", u"RM recusada" in (e.get("erro") or u""),
           e)
    m = cli.post("/api/bolus/abrir", json={"b": b}).json()
    checar(u"abrir a TC devolve a geometria e a caixa inicial",
           not m.get("erro") and "caixa" in m and m.get("sem_mesa"), m)
    pv = m["previa"]
    v = cli.get("/api/bolus/volume", params={"b": b, "qual": "corpo"})
    checar(u"a prévia do corpo tem o tamanho declarado",
           v.status_code == 200 and len(v.content) == int(np.prod(pv["forma"])))
    c = cli.get("/api/bolus/corte", params={"b": b, "plano": "co", "i": 60})
    checar(u"o corte coronal responde em PNG",
           c.status_code == 200 and c.content[:4] == b"\x89PNG")
    checar(u"(isca) bilhete desconhecido não abre corte",
           cli.get("/api/bolus/corte", params={"b": "0" * 32}).status_code
           == 404)
    cx = m["caixa"]
    g = cli.post("/api/bolus/gerar", json={
        "b": b, "caixa": cx, "modo": "anatomico", "espessura": 4,
        "suavizacao": 1.0, "direcao": "auto", "marcas": True}).json()
    checar(u"gerar devolve o resumo com o id", g.get("r") and
           g.get("malha", {}).get("fechada"), g)
    checar(u"o resumo não carrega caminho nem nome",
           base not in json.dumps(g) and u"ZZSENTINELA" not in json.dumps(g))
    rid = g.get("r")
    sem = cli.post("/api/bolus/stl", json={"b": b, "r": rid})
    checar(u"SEM o ato, o STL é recusado com 409", sem.status_code == 409,
           sem.status_code)
    trocada = cli.post("/api/bolus/stl", json={"b": b, "r": rid,
                                                "declaro": True,
                                                "frase": u"ok"})
    checar(u"com a frase trocada, também", trocada.status_code == 409)
    def ler_atos():
        try:
            return io.open(T.arquivo_de_atos(), encoding="utf-8").read()
        except IOError:
            return u""

    ATO = {"b": b, "r": rid, "declaro": True, "frase": B.FRASE_DO_ATO}
    com = cli.post("/api/bolus/stl", json=ATO)
    checar(u"COM o ato, sai o STL", com.status_code == 200
           and B.cabecalho_seguro(com.content[:80]), com.status_code)
    cd = com.headers.get("content-disposition", u"")
    nome = com.headers.get("x-radai-nome", u"")
    checar(u"o nome do arquivo não leva nada da série (%s)" % cd,
           u"RadAI_bolus_DRAFT_anatomical_4mm_" in cd and u"ZZ" not in cd)
    atos = ler_atos()
    checar(u"o ato fica escrito no ARQUIVO dos atos, com o nome do STL",
           u"exportado por ato declarado" in atos and nome and nome in atos,
           atos[-200:])
    checar(u"e o arquivo não leva pasta nem nome do paciente",
           base not in atos and u"ZZSENTINELA" not in atos
           and u"ZZ0001" not in atos)
    checar(u"e o log do vigia (o `registrar` injetado) recebe a mesma linha",
           len(ouvidos) == 1 and nome in ouvidos[0], ouvidos)
    gravar = T._gravar_ato
    try:
        T._gravar_ato = lambda linha: None
        antes = ler_atos()
        mudo = cli.post("/api/bolus/stl", json=ATO)
        depois = ler_atos()
    finally:
        T._gravar_ato = gravar
    checar(u"(isca) sem a gravação, o arquivo não ganha a linha — e a "
           u"checagem acima reprovaria", mudo.status_code == 200
           and depois == antes)
    def quebra(linha):
        raise IOError("disco cheio (dublado)")
    try:
        T._gravar_ato = quebra
        falhou = cli.post("/api/bolus/stl", json=ATO)
    finally:
        T._gravar_ato = gravar
    checar(u"sem conseguir registrar o ato, o STL NÃO sai (500, sem bytes "
           u"de STL)", falhou.status_code == 500
           and not B.cabecalho_seguro(falhou.content[:80])
           and u"registrado" in (falhou.json().get("erro") or u""),
           falhou.status_code)
    checar(u"a rota grava o ato ANTES de montar a resposta",
           _rota_chama_antes(io.open(_componentes.fonte("app/radai_bolus_screen.py"),
                                     encoding="utf-8").read(),
                             "/api/bolus/stl", "_gravar_ato"))
    de_novo = cli.post("/api/bolus/stl", json={"b": b, "r": rid})
    checar(u"a declaração NÃO fica lembrada: a próxima sem ato é recusada",
           de_novo.status_code == 409)
    vb = cli.get("/api/bolus/volume", params={"b": b, "qual": "bolus",
                                               "r": rid})
    checar(u"a prévia do bólus tem o tamanho declarado",
           vb.status_code == 200 and
           len(vb.content) == int(np.prod(g["previa"]["forma"])))
    checar(u"sem molde pedido, o resumo diz molde nulo", g.get("molde") is None)
    sem_molde = cli.post("/api/bolus/stl", json=dict(ATO, peca="molde"))
    checar(u"pedir o STL do molde de um bólus gerado sem ele: 404",
           sem_molde.status_code == 404
           and u"sem molde" in (sem_molde.json().get("erro") or u""))
    gm = cli.post("/api/bolus/gerar", json={
        "b": b, "caixa": cx, "modo": "anatomico", "espessura": 4,
        "suavizacao": 1.0, "direcao": "auto", "marcas": True,
        "molde": True, "casca": 2, "abertura": "superior"}).json()
    mo = gm.get("molde") or {}
    checar(u"gerar com o molde devolve o resumo dele, sem bytes nem máscara",
           mo.get("malha", {}).get("fechada") and mo.get("exportavel")
           and "stl" not in mo and "mask" not in mo
           and mo.get("bytes_stl", 0) > 84, sorted(mo)[:12])
    checar(u"«molde» em texto não liga o molde (só `true`)",
           cli.post("/api/bolus/gerar", json={
               "b": b, "caixa": cx, "modo": "anatomico", "espessura": 4,
               "suavizacao": 1.0, "direcao": "auto", "marcas": False,
               "molde": "false"}).json().get("molde") is None)
    gm = cli.post("/api/bolus/gerar", json={
        "b": b, "caixa": cx, "modo": "anatomico", "espessura": 4,
        "suavizacao": 1.0, "direcao": "auto", "marcas": True,
        "molde": True, "casca": 2, "abertura": "superior"}).json()
    rm = gm.get("r")
    ATO_M = {"b": b, "r": rm, "declaro": True, "frase": B.FRASE_DO_ATO,
             "peca": "molde"}
    checar(u"o STL do molde SEM o ato: 409",
           cli.post("/api/bolus/stl", json={"b": b, "r": rm,
                                            "peca": "molde"}).status_code
           == 409)
    checar(u"peça desconhecida: 409",
           cli.post("/api/bolus/stl", json=dict(ATO_M, peca="tampa"))
           .status_code == 409)
    antes = ler_atos()
    cm = cli.post("/api/bolus/stl", json=ATO_M)
    nome_m = cm.headers.get("x-radai-nome", u"")
    checar(u"COM o ato, sai o STL do molde, com o cabeçalho do molde",
           cm.status_code == 200
           and cm.content[:80] == B.CABECALHO_STL_MOLDE.ljust(80, b" ")
           and B.cabecalho_seguro(cm.content[:80]), cm.status_code)
    checar(u"o nome do molde diz o que é, e nada da série (%s)" % nome_m,
           u"_MOLD_wall2mm_open-superior_" in nome_m and u"ZZ" not in nome_m
           and nome_m.endswith(rm[:8] + u".stl"))
    novo = ler_atos()[len(antes):]
    checar(u"o ato do molde fica escrito no arquivo dos atos, sem a série",
           u"STL do MOLDE exportado por ato declarado" in novo
           and nome_m in novo and base not in novo
           and u"ZZSENTINELA" not in novo, novo[-200:])
    checar(u"e chega ao log do vigia também",
           ouvidos and nome_m in ouvidos[-1], ouvidos[-1:])
    checar(u"a rota do STL continua conferindo o ato ANTES de montar a "
           u"resposta, para as duas peças",
           _rota_chama_antes(io.open(_componentes.fonte("app/radai_bolus_screen.py"),
                                     encoding="utf-8").read(),
                             "/api/bolus/stl", "conferir_ato"))
    vm = cli.get("/api/bolus/volume", params={"b": b, "qual": "molde",
                                               "r": rm})
    checar(u"a prévia do molde tem o tamanho declarado",
           vm.status_code == 200 and
           len(vm.content) == int(np.prod(mo["previa"]["forma"])))
    c2 = cli.get("/api/bolus/corte", params={"b": b, "plano": "ax",
                                             "i": 26, "r": rm})
    checar(u"o corte com o molde responde em PNG",
           c2.status_code == 200 and c2.content[:4] == b"\x89PNG")
    pasta_tc = os.path.join(base, "PAC", "CT")
    checar(u"o cabeçalho diz linhas × colunas × cortes sem ler a série",
           T._voxels_pelo_cabecalho(pasta_tc, None) == 170 * 170 * 52,
           T._voxels_pelo_cabecalho(pasta_tc, None))
    import engine
    lidas = []
    carregar, teto = engine.load_sitk, B.TETO_SERIE_VOXELS
    try:
        engine.load_sitk = lambda *a, **k: lidas.append(1) or carregar(*a, **k)
        B.TETO_SERIE_VOXELS = 1000
        grande = cli.post("/api/bolus/abrir", json={"b": b}).json()
    finally:
        engine.load_sitk, B.TETO_SERIE_VOXELS = carregar, teto
    checar(u"série acima do teto: recusada ANTES de ler um pixel",
           u"grande demais" in (grande.get("erro") or u"") and not lidas,
           (grande, lidas))
    T._esquecer()


def teste_costura_do_registro():
    secao(u"o painel injeta o log do vigia na rota do STL (a costura real)")
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as e:
        checar(u"fastapi.testclient disponível", False, e)
        return
    import radai_bolus_screen as T
    import radai_panel

    def exporta(config):
        app = FastAPI()
        radai_panel.montar(app, ler_vigia=lambda: {}, config=config)
        cli = TestClient(app)
        serie = object()
        T._esquecer()
        T._S.update({"b": "bcostura", "serie": serie, "visto": time.time()})
        res = {"modo": "anatomico", "espessura_mm": 3, "suavizacao_mm": 0.0,
               "malha": {"fechada": True, "triangulos": 1}, "espessura": None,
               "stl": B.CABECALHO_STL[:80].ljust(80, b" ") + b"\x00" * 4}
        rid = T._publicar("bcostura", serie, res)
        r = cli.post("/api/bolus/stl", json={"b": "bcostura", "r": rid,
                                              "declaro": True,
                                              "frase": B.FRASE_DO_ATO})
        T._esquecer()
        return r.status_code

    ouvidos = []
    st = exporta({"registrar": ouvidos.append})
    checar(u"montado pelo painel, o ato chega ao `registrar` do vigia",
           st == 200 and len(ouvidos) == 1
           and u"exportado por ato declarado" in ouvidos[0], (st, ouvidos))
    antes = io.open(T.arquivo_de_atos(), encoding="utf-8").read() \
        if os.path.exists(T.arquivo_de_atos()) else u""
    st2 = exporta({})
    depois = io.open(T.arquivo_de_atos(), encoding="utf-8").read()
    checar(u"(isca) sem o `registrar` na costura, o log do vigia não ouve "
           u"nada — mas o arquivo dos atos ganha a linha",
           st2 == 200 and len(ouvidos) == 1 and len(depois) > len(antes))


def teste_corrida():
    secao(u"a corrida: abrir outra série durante a geração não troca o STL")
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except Exception as e:
        checar(u"fastapi.testclient disponível", False, e)
        return
    import radai_bolus_screen as T

    class SerieFalsa(object):
        def __init__(self, nome):
            self.nome = nome

    def falso(serie):
        return {"modo": "anatomico", "espessura_mm": 5, "suavizacao_mm": 0.0,
                "malha": {"fechada": True, "triangulos": 1},
                "espessura": None,
                "stl": B.CABECALHO_STL[:80].ljust(80, b" ")
                + b"\x00\x00\x00\x00" + b"SERIE-" + serie.nome.encode(),
                "mask": None, "previa": {}, "grade_mm": 1.0, "off": [0, 0, 0]}

    def cenario():
        A, Bs = SerieFalsa("A"), SerieFalsa("B")
        T._esquecer()
        T._S.update({"b": "bilheteA", "serie": A, "visto": time.time()})

        def gerar_lento(serie, *a, **k):
            with T._TRAVA:
                T._esquecer()
                T._S.update({"b": "bilheteB", "serie": Bs,
                             "visto": time.time()})
            return falso(serie)

        gerar, resumo = B.gerar, B.resumo
        try:
            B.gerar, B.resumo = gerar_lento, (lambda res: {})
            app = FastAPI()
            T.montar(app)
            cli = TestClient(app)
            g = cli.post("/api/bolus/gerar", json={"b": "bilheteA"}).json()
            stl = cli.post("/api/bolus/stl", json={
                "b": "bilheteB", "r": g.get("r") or "x" * 16,
                "declaro": True, "frase": B.FRASE_DO_ATO})
        finally:
            B.gerar, B.resumo = gerar, resumo
        return g, stl

    g, stl = cenario()
    checar(u"a geração da A termina RECUSADA (a série mudou)",
           u"mudou durante a geração" in (g.get("erro") or u"")
           and not g.get("r"), g)
    checar(u"o resultado da A NÃO fica pendurado na B",
           T._S.get("b") == "bilheteB" and T._S.get("res") is None)
    checar(u"e o STL pedido com o bilhete da B não sai com a A dentro",
           stl.status_code != 200 and b"SERIE-A" not in stl.content,
           stl.status_code)
    publicar = T._publicar

    def publicar_velho(b, serie, res):
        rid = B.sorteio()
        with T._TRAVA:
            T._S["res"], T._S["r"], T._S["visto"] = res, rid, time.time()
        return rid

    try:
        T._publicar = publicar_velho
        g2, stl2 = cenario()
    finally:
        T._publicar = publicar
    checar(u"(isca) sem a conferência, o STL da A sai com o bilhete da B",
           g2.get("r") and stl2.status_code == 200
           and stl2.content.endswith(b"SERIE-A"), (g2, stl2.status_code))
    A = SerieFalsa("A")
    T._esquecer()
    T._S.update({"b": "bilheteA", "serie": A, "visto": time.time()})
    try:
        T._publicar("bilheteA", SerieFalsa("A"), falso(A))
        ok = False
    except B.Recusa:
        ok = True
    checar(u"reabrir a MESMA série cria outra — e o resultado antigo não serve",
           ok and T._S.get("res") is None)
    js = T.JS
    i = js.index(u"el('bo-gerar').onclick")
    trecho = js[i:js.index(u"\n};\n", i)]
    checar(u"o JS guarda o bilhete no clique e descarta a resposta de outra "
           u"série", u"var b = BO.b;" in trecho
           and u"if(BO.b !== b) return;" in trecho
           and u"BO.gerando = true" in trecho)
    checar(u"e o «Abrir» fica desligado enquanto se gera",
           u"BO.gerando ||" in js[js.index(u"function liberarAbrir"):]
           .split(u"}")[0])
    isca = trecho.replace(u"if(BO.b !== b) return;", u"")
    checar(u"(isca) sem o descarte, a checagem do JS reprova",
           u"if(BO.b !== b) return;" not in isca)
    checar(u"no modo Caixa a tela NÃO manda espessura",
           u"espessura: modo === 'caixa' ? null" in js)
    T._esquecer()


def teste_lugares_de_modulo():
    secao(u"a suíte conhece o módulo, nos cinco lugares")
    import radai_breadcrumb
    import radai_menu
    import radai_modules
    import radai_ui
    checar(u"1· a trilha sabe onde ele mora",
           radai_breadcrumb.ARVORE.get("bolus", (None, None))[1] == "/bolus")
    checar(u"   e onde mora a ferramenta",
           radai_breadcrumb.ARVORE.get("bolus_gerar", (0, 0, 0))[1:]
           == ("/bolus/gerar", "bolus"))
    checar(u"2· o trilho o lista", "bolus" in radai_menu.MODULOS)
    checar(u"   e a home também", "bolus" in radai_menu.MODULOS_HOME)
    checar(u"   e o registro de telas tem as duas",
           {"bolus", "bolus_gerar"} <= {i[0] for i in radai_menu.ITENS})
    for d in ("CORES", "MODULOS", "FERRAMENTAS", "AJUDA", "SEM_EXPORTACAO"):
        checar(u"3· radai_modules.%s o conhece" % d,
               "bolus" in getattr(radai_modules, d))
    css = radai_ui.TOKENS
    checar(u"4· a cor existe nos DOIS temas",
           css.count("--mod-bolus:") >= 2 and css.count("--mod-bolus-txt:") >= 2)
    checar(u"5· o painel monta a tela",
           '"radai_bolus_screen"' in ler("app/radai_panel.py"))
    checar(u"   e o roteador serve a mini-página",
           '("bolus", "/bolus")' in ler("app/radai_router.py"))
    import radai_porta
    linha = radai_porta.cartao("bolus", 5)
    checar(u"o cartão da porta aponta para /bolus", 'href="/bolus"' in linha,
           linha[:80])
    p = radai_modules.pagina("bolus")
    # GUARDA: o texto longo do que sai mora no `?` do título; a não-validação clínica mora na porta e no `?`.
    _bal = u" ".join(u" ".join(v) for v in radai_modules.secoes_de_ajuda("bolus").values())
    checar(u"a mini-página diz o que sai, no `?` do título",
           u"exporta um STL" in _bal and u"ui-balao" in p)
    _lin = radai_modules.MODULOS["bolus"]["linha"]
    checar(u"e o alerta do módulo diz o ato declarado e a dosimetria",
           u"ato declarado" in _lin and u"dosimetria do material" in _lin)
    checar(u"e o `?` diz «não é para uso clínico»",
           u"para uso clínico" in _bal)
    n = ler("NOTICE")
    checar(u"o NOTICE tem a linha de origem do porte do DeFace RT",
           u"DeFace RT" in n and u"radai_bolus_screen" in n)


PENDENTES_DE_TRADUCAO = ()


def teste_traducoes():
    secao(u"toda frase das duas telas do módulo tem chave (12 idiomas)")
    import radai_menu
    import radai_modules
    import radai_phrases as F
    import radai_bolus_screen as T
    sys.path.insert(0, AQUI)
    import test_languages as TL
    chaves = set(F.normalizar(l[0]) for l in F.TABELA)
    pend = set(F.normalizar(f) for f in PENDENTES_DE_TRADUCAO)
    vistas = set()
    for nome, pag in ((u"/bolus/gerar", radai_menu.aplicar(T.pagina(),
                                                           "bolus_gerar")),
                      (u"/bolus", radai_menu.aplicar(
                          radai_modules.pagina_completa("bolus"), "bolus",
                          com_tarefas=False))):
        frases = list(TL._frases_visiveis(pag))
        vistas.update(frases)
        sem = [f for f in frases if f not in chaves and f not in pend]
        checar(u"%s: todas as %d frases têm chave (fora as %d pendentes "
               u"da onda 2, declaradas)" % (nome, len(frases), len(pend)),
               not sem, u" | ".join(sem[:5]))
    consts = set()
    for rel in ("app/radai_bolus_screen.py", "app/radai_bolus_aplicador.py"):
        fonte = io.open(_componentes.fonte(rel), encoding="utf-8").read()
        consts |= set(F.normalizar(n.value)
                      for n in ast.walk(ast.parse(fonte))
                      if isinstance(n, ast.Constant)
                      and isinstance(n.value, str))
    fonte_js = F.normalizar(T.JS)
    stale = [f for f in pend if f not in vistas and f not in fonte_js
             and f not in consts]
    checar(u"toda frase pendente está mesmo na tela ou no código",
           not stale, stale[:3])
    ja = [f for f in pend if f in chaves]
    checar(u"nenhuma pendente já tem chave (a resolvida sai da lista)",
           not ja, ja[:3])
    checar(u"(isca) uma frase nova sem chave e fora da lista seria acusada",
           F.normalizar(u"frase nova do molde ZZQ") not in chaves
           and F.normalizar(u"frase nova do molde ZZQ") not in pend)
    for f in (u"informe a pasta", u"abrindo a série…",
              u"gerando o bólus…", u"arraste para girar",
              u"A caixa ou os parâmetros mudaram: gere de novo para exportar.",
              u"espessura mínima", u"espessura mediana", u"espessura máxima",
              u"volume do material", u"malha fechada", u"triângulos",
              u"peças", u"grade de trabalho", u"direção de colocação",
              u"marcas de lado", u"dimensões", u"tempo",
              u"A malha não fechou: o STL não é exportado.",
              u"Nenhuma série nesta pasta.",
              u"contorno externo sem remoção de mesa",
              u"A série mudou durante a geração: este bólus era da série "
              u"anterior e foi descartado. Gere de novo.",
              u"sim", u"não", u"raio padrão", u"face de entrada",
              u"Face de entrada do cateter (as distâncias contam dela)",
              u"fundo cego: só a face de entrada é aberta",
              u"%s mm (o sugerido é %s mm)"):
        checar(u"a frase do JS «%s» tem chave" % f[:40],
               F.normalizar(f) in chaves)
    T._esquecer()
    try:
        T._publicar("outro", object(), {})
        viva = u""
    except B.Recusa as e:
        viva = str(e)
    checar(u"a recusa da corrida, como o código a escreve, tem chave",
           viva and F.normalizar(viva) in chaves, viva)
    minhas = [l for l in F.TABELA if l[0] in (
        B.ALERTA, B.FRASE_DO_ATO, B.AVISO_BIOMETRIA, u"Gerar bólus")]
    checar(u"as frases de fronteira têm as 11 traduções",
           len(minhas) == 4 and all(len(l) == 12 and all(l[1:]) for l in minhas),
           [l[0][:20] for l in minhas])
    isca = u"frase inventada que nenhuma tabela tem ZZQ"
    checar(u"(isca) a checagem reprova frase sem chave",
           F.normalizar(isca) not in chaves)


_MEDIDOR = r'''
import ctypes, ctypes.wintypes as W, json, sys, threading, time
class PMC(ctypes.Structure):
    _fields_ = [("cb", W.DWORD), ("PageFaultCount", W.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
                ("PrivateUsage", ctypes.c_size_t)]
k32 = ctypes.WinDLL("kernel32")
k32.GetCurrentProcess.restype = W.HANDLE
info = k32.K32GetProcessMemoryInfo
info.argtypes = [W.HANDLE, ctypes.POINTER(PMC), W.DWORD]
info.restype = W.BOOL
def mem():
    c = PMC(); c.cb = ctypes.sizeof(PMC)
    if not info(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise OSError("GetProcessMemoryInfo")
    return c.PrivateUsage, c.PeakPagefileUsage
def pico(f):
    u"""O pico ACIMA da base durante f(): o maior entre o contador de pico do
    sistema (se ele subiu) e uma amostragem de 1 ms, que vê o que o contador
    não mostra quando o pico do processo já estava acima."""
    time.sleep(0.05)
    base, pk0 = mem()
    amostra, fim = [base], [False]
    def ver():
        while not fim[0]:
            amostra[0] = max(amostra[0], mem()[0]); time.sleep(0.001)
    th = threading.Thread(target=ver); th.daemon = True; th.start()
    r = f()
    fim[0] = True; th.join()
    _b, pk1 = mem()
    topo = max(amostra[0], pk1 if pk1 > pk0 else 0)
    return r, (topo - base) / 1048576.0
sys.path.insert(0, sys.argv[1])
import numpy as np, SimpleITK as sitk
import scipy.ndimage, scipy.spatial          # o custo de importar não é do gerar
import radai_bolus as B
s = B.abrir(sitk.ReadImage(sys.argv[2]), "CT")
lo = [float(v) for v in sys.argv[3].split(",")[0::2]]
hi = [float(v) for v in sys.argv[3].split(",")[1::2]]
cant = np.array([[a, b, c] for a in (lo[0], hi[0]) for b in (lo[1], hi[1])
                 for c in (lo[2], hi[2])])
q = s.lps_para_quadro(cant)
cx = {"x0": q[:, 0].min(), "x1": q[:, 0].max(), "y0": q[:, 1].min(),
      "y1": q[:, 1].max(), "z0": q[:, 2].min(), "z1": q[:, 2].max()}
molde = len(sys.argv) > 4 and sys.argv[4] == "1"
res, mib = pico(lambda: B.gerar(s, cx, "caixa", None, 1.0, "ant", True,
                                molde=molde, casca_mm=2, abertura="superior"))
out = {"pico_mib": mib, "voxels": int(np.prod(res["forma"])),
       "grade": res["grade_mm"], "tri": res["malha"]["triangulos"],
       "dsc": res["dsc_ida_volta"], "fechada": res["malha"]["fechada"]}
if molde:
    m = res["molde"]
    out.update(tri_molde=m["malha"]["triangulos"], dsc=m["dsc_ida_volta"],
               fechada=m["malha"]["fechada"] and res["malha"]["fechada"])
del res
# a ISCA: uma alocação do SimpleITK do tamanho do orçamento + 64 MiB, que o
# `tracemalloc` não veria. O medidor tem de ver.
n = int(B.ORCAMENTO_PICO_MIB + 64)
def isca():
    im = sitk.Image([1024, 1024 * n], sitk.sitkUInt8)   # n MiB, em 2D
    time.sleep(0.05)
    return im.GetNumberOfPixels()
_r, out["isca_mib"] = pico(isca)
print("RESULTADO " + json.dumps(out))
'''


def teste_pico_de_memoria():
    secao(u"o pico de memória perto do teto, num processo à parte")
    if os.name != "nt":
        print(u"         · só no Windows (a medida é o GetProcessMemoryInfo)")
        return
    import subprocess
    import SimpleITK as sitk
    pasta = _cleanup.temporaria("radai_teste_bolus_pico_")
    arq = os.path.join(pasta, "fantoma.mha")
    sitk.WriteImage(fantoma(sentinela=False), arq)
    caixa = "-95,95,-99,90,-72,72"
    p = subprocess.run([sys.executable, "-c", _MEDIDOR, APP, arq, caixa],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=600)
    saida = p.stdout.decode("utf-8", "replace")
    linha = [l for l in saida.splitlines() if l.startswith("RESULTADO ")]
    if not linha:
        checar(u"o medidor rodou", False,
               p.stderr.decode("utf-8", "replace")[-300:])
        return
    r = json.loads(linha[0][len("RESULTADO "):])
    print(u"         · %.1f M voxels a %.1f mm, %d triângulos: pico de %.0f MiB"
          u" acima da base" % (r["voxels"] / 1e6, r["grade"], r["tri"],
                               r["pico_mib"]))
    checar(u"a caixa medida está perto do teto (≥ 85%% de %d M voxels)"
           % (B.TETO_VOXELS // 1000000),
           r["voxels"] >= 0.85 * B.TETO_VOXELS and r["fechada"]
           and r["dsc"] >= 0.9999, r)
    checar(u"o pico fica no orçamento de %d MiB (medido: %.0f; a versão "
           u"anterior passava de 900)" % (B.ORCAMENTO_PICO_MIB, r["pico_mib"]),
           0 < r["pico_mib"] <= B.ORCAMENTO_PICO_MIB, r)
    checar(u"(isca) uma alocação do SimpleITK de orçamento + 64 MiB estoura "
           u"a mesma régua (%.0f MiB)" % r["isca_mib"],
           r["isca_mib"] > B.ORCAMENTO_PICO_MIB, r)
    p2 = subprocess.run([sys.executable, "-c", _MEDIDOR, APP, arq,
                         "-75,75,-99,25,-55,55", "1"],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        timeout=900)
    linha = [l for l in p2.stdout.decode("utf-8", "replace").splitlines()
             if l.startswith("RESULTADO ")]
    if not linha:
        checar(u"o medidor do molde rodou", False,
               p2.stderr.decode("utf-8", "replace")[-300:])
        return
    m = json.loads(linha[0][len("RESULTADO "):])
    print(u"         · molde: %.1f M voxels, %d triângulos de bólus e %d de "
          u"molde: pico de %.0f MiB acima da base"
          % (m["voxels"] / 1e6, m["tri"], m["tri_molde"], m["pico_mib"]))
    checar(u"a caixa do molde está perto do teto dele (≥ 85%% de %d M voxels)"
           % (B.TETO_MOLDE_VOXELS // 1000000),
           m["voxels"] >= 0.85 * B.TETO_MOLDE_VOXELS
           and m["voxels"] <= B.TETO_MOLDE_VOXELS and m["fechada"]
           and m["dsc"] >= 0.9999, m)
    checar(u"bólus + molde ficam no mesmo orçamento de %d MiB (medido: %.0f)"
           % (B.ORCAMENTO_PICO_MIB, m["pico_mib"]),
           0 < m["pico_mib"] <= B.ORCAMENTO_PICO_MIB, m)


def _cronometrar(f, *a):
    t0 = time.time()
    r = f(*a)
    print(u"         · %.1f s" % (time.time() - t0))
    return r


def main():
    print(u"=" * 68)
    print(u"test_bolus | o bólus impresso em 3D: malha, lado, espessura, ato")
    print(u"=" * 68)
    os.environ["RADAI_CALIB_DIR"] = _cleanup.temporaria(
        "radai_teste_bolus_acervo_")
    for f in (teste_superficie, teste_ponto_triangulo, teste_voxelizar,
              teste_stl, teste_em_fatias, teste_distancia_float32,
              teste_serie_sem_copia,
              teste_eixos_da_marca, teste_ato, teste_face,
              teste_a_faixa_tem_a_letra):
        _cronometrar(f)
    secao(u"os fantomas: HFS, FFS, oblíquo e matriz imprópria")
    t0 = time.time()
    series = {
        "HFS": B.abrir(fantoma(), "CT"),
        "FFS": B.abrir(fantoma(D=np.diag([-1.0, 1.0, -1.0])), "CT"),
        "obliqua": B.abrir(fantoma(D=rot("z", 11).dot(rot("x", 17)),
                                   forma=(214, 214, 58)), "CT"),
        "impropria": B.abrir(fantoma(D=np.diag([1.0, 1.0, -1.0])), "CT"),
    }
    print(u"         · quatro séries abertas em %.1f s" % (time.time() - t0))
    _cronometrar(teste_quadro_e_matriz, series)
    _cronometrar(teste_corte_na_orientacao_de_leitura, series)
    res = _cronometrar(teste_bolus_anatomico, series)
    _cronometrar(teste_espelho_do_stl, res["HFS"])
    _cronometrar(teste_suavizacao, series, res["HFS"])
    for f in (teste_marcas, teste_modo_caixa, teste_matriz_impropria,
              teste_sem_phi, teste_recusas, teste_previa_e_corte,
              teste_faixa_da_espessura, teste_rente_ao_no):
        _cronometrar(f, series)
    moldes = _cronometrar(teste_molde_aberturas, series)
    for f in (teste_molde_casca, teste_molde_interior, teste_molde_fechado,
              teste_molde_no_corte):
        _cronometrar(f, series, moldes)
    for f in (teste_molde_grade, teste_molde_fragmento,
              teste_molde_recusas_e_nome):
        _cronometrar(f, series)
    for f in (teste_tela, teste_o_popup_da_serie, teste_nomes_acessiveis, teste_js_do_3d, teste_rotas,
              teste_costura_do_registro, teste_corrida,
              teste_lugares_de_modulo, teste_traducoes,
              teste_pico_de_memoria):
        _cronometrar(f)
    print(u"\n" + u"=" * 68)
    if _falhas:
        print(u"FALHOU: %d de %d checagens" % (len(_falhas),
                                                len(_falhas) + _ok[0]))
        for f in _falhas:
            print(u"  - %s" % f)
        print(u"=" * 68)
        sys.exit(1)
    print(u"OK: %d checagens, todas passaram" % _ok[0])
    print(u"=" * 68)


if __name__ == "__main__":
    main()
