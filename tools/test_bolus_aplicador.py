# -*- coding: utf-8 -*-
import ast
import io
import json
import math
import os
import re
import sys
import time
import zipfile

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
import _componentes
import radai_bolus as B
import radai_bolus_aplicador as A

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
        print(u"  FALHA  %s  %s" % (nome, str(detalhe).replace("\n", " ")[:240]))


def secao(t):
    print(u"\n-- %s %s" % (t, u"-" * max(0, 60 - len(t))))


def recusa(f, *a, **k):
    try:
        f(*a, **k)
    except B.Recusa as e:
        return e
    return None


def cilindro(R=80.0, L=80.0, esp=(1.0, 1.0, 2.0), meia=(110.0, 110.0, 100.0),
             sentinela=True):
    nx, ny, nz = [int(round(2 * meia[i] / esp[i])) + 1 for i in range(3)]
    x = (np.arange(nx) - (nx - 1) / 2.0) * esp[0]
    y = (np.arange(ny) - (ny - 1) / 2.0) * esp[1]
    z = (np.arange(nz) - (nz - 1) / 2.0) * esp[2]
    Z, Y, X = np.meshgrid(z, y, x, indexing="ij")
    sd = np.maximum(np.sqrt(X ** 2 + Y ** 2) - R, np.abs(Z) - L)
    frac = np.clip(0.5 - sd / min(esp), 0.0, 1.0)
    img = sitk.GetImageFromArray((-1000.0 + 1020.0 * frac).astype(np.int16))
    img.SetSpacing(tuple(float(e) for e in esp))
    img.SetOrigin((float(x[0]), float(y[0]), float(z[0])))
    if sentinela:
        img.SetMetaData("0010|0010", "ZZSENTINELA^ISCA^APLICADOR")
    return img


def caixa(s, lo, hi):
    cant = np.array([[a, b, c] for a in (lo[0], hi[0]) for b in (lo[1], hi[1])
                     for c in (lo[2], hi[2])], dtype=np.float64)
    q = s.lps_para_quadro(cant)
    return {"x0": q[:, 0].min(), "x1": q[:, 0].max(), "y0": q[:, 1].min(),
            "y1": q[:, 1].max(), "z0": q[:, 2].min(), "z1": q[:, 2].max()}


def tri_lps(stl):
    return B.ler_stl(stl)[1]


def linhas_lps(s, res):
    return [s.quadro_para_lps(np.array(l)) for l in
            res["linhas_centrais_quadro"]]


FORA_DA_BIBLIOGRAFIA = (u"Straath" + u"of", u"Schuma" + u"cher", u"NR" + u"C")


def teste_padroes_e_menus():
    secao(u"os padrões, os menus com os nomes, e os pisos")
    p = A.padroes()
    checar(u"cateter 6F (2,0 mm), canal = diâmetro externo + 1,0 mm = 3,0 mm",
           p["cateter"] == "6f" and A.DIAMETRO_6F_MM == 2.0
           and abs(p["canal_mm"] - 3.0) < 1e-9 and A.FOLGA_PADRAO_MM == 1.0,
           p)
    checar(u"eixo a 5 mm da pele, 10 mm entre canais, corpo de 10 mm",
           (p["distancia_mm"], p["espacamento_mm"], p["corpo_mm"])
           == (5.0, 10.0, 10.0), p)
    checar(u"trajeto aberto, entrada afunilada, raio padrão de 35 mm",
           p["trajeto"] == "aberto" and p["funil"] is True
           and A.RAIO_PADRAO_MM == 35.0 and p["raio_padrao_mm"] == 35.0)
    checar(u"cada opção dos dois menus tem a fonte curta",
           all(len(x.get("curta") or u"") > 5
               for x in A.AFTERLOADERS + A.CATETERES))
    al = [(a["nome"], a["piso_mm"]) for a in A.AFTERLOADERS]
    checar(u"os afterloaders, na ordem, com o piso de cada um",
           al == [(u"microSelectron Digital", 13.0), (u"Flexitron", 17.0),
                  (u"GammaMed iX", 13.0), (u"Bravos", 13.0),
                  (u"VariSource iX", 17.0), (u"outro ou não sei", 17.0)], al)
    ca = [(c["nome"], c["piso_mm"]) for c in A.CATETERES]
    checar(u"os cateteres: 6F (15 mm), ProGuide com obturador (35 mm), outro",
           ca == [(u"tubo flexível 6F", 15.0),
                  (u"ProGuide com obturador", 35.0), (u"outro", 35.0)], ca)
    vx = [a for a in A.AFTERLOADERS if a["chave"] == "varisource_ix"][0]
    checar(u"o VariSource iX diz que o número NÃO foi conferido, no «?» e "
           u"na própria opção do menu",
           vx["conferido"] is False and u"NÃO conferido" in vx["fonte"]
           and u"NÃO conferido" in vx["curta"])
    checar(u"(isca) as opções conferidas não dizem «NÃO conferido»",
           not any(u"NÃO conferido" in a["curta"] for a in A.AFTERLOADERS
                   if a["conferido"]))
    raio = u" ".join(A.AJUDA["raio"])
    checar(u"o «?» do raio explica o 35 e o 50 (os dois de Laan 2019) e a "
           u"curva plana do fabricante",
           u"Laan 2019" in raio
           and u"35 mm" in raio and u"50 mm" in raio
           and u"curva só, plana e favorável" in raio, raio[:120])
    def diz_a_regra(t):
        return (u"pode subir o padrão" in t
                and u"Abaixo de 35 mm o campo não desce" in t
                and u"sempre amarela" in t and u"segunda declaração" in t
                and u"abaixo do piso do equipamento o app não gera" in t
                and u"Descer, só até o piso" not in t)
    checar(u"e diz que o físico pode subir o padrão, que abaixo de 35 mm o "
           u"campo não desce e a curva é sempre amarela, e que abaixo do piso "
           u"não gera", diz_a_regra(raio), raio[:200])
    velho = (u"O físico pode subir o padrão, por exemplo para 50 mm, e a curva "
             u"amarela passa a valer até ele. Descer, só até o piso do "
             u"equipamento, que bloqueia; abaixo dos 35 mm sugeridos, a ficha "
             u"avisa.")
    checar(u"(isca) o «?» antigo, que deixava descer o padrão até o piso, "
           u"seria acusado", not diz_a_regra(raio.replace(
               A.AJUDA["raio"][1], velho)) and A.AJUDA["raio"][1] in raio)
    af = u" ".join(A.AJUDA["afterloader"])
    checar(u"o «?» do afterloader traz o número e a fonte de cada um",
           all((u"%s: %d mm" % (a["nome"], int(a["piso_mm"]))) in af
               and a["fonte"] in af for a in A.AFTERLOADERS))
    ct = u" ".join(A.AJUDA["cateter"])
    checar(u"e o do cateter também",
           all((u"%s: %d mm" % (c["nome"], int(c["piso_mm"]))) in ct
               for c in A.CATETERES))
    for chave in ("canal", "distancia", "espacamento", "corpo", "trajeto",
                  "funil", "material", "eixo", "entrada", "aplicador", "od",
                  "direcao", "superficie"):
        checar(u"o «?» de «%s» existe e diz alguma coisa" % chave,
               len(u" ".join(A.AJUDA.get(chave, ()))) > 60)
    sup = u" ".join(A.AJUDA["superficie"])
    checar(u"o «?» da superfície diz qual pele vale (o limiar fixo de %d HU, "
           u"o mesmo do radai_skin)" % int(B.LIMIAR_HU),
           (u"limiar fixo de %d HU" % int(B.LIMIAR_HU)) in sup
           and B.LIMIAR_HU == -300.0, sup[:120])
    checar(u"e que a janela de exibição não muda a pele usada, com a janela "
           u"da TC de Bellis (1 a 2 mm)",
           u"só mudam a exibição" in sup and u"1 a 2 mm" in sup)
    checar(u"e que a distância e a curva do canal seguem a borda do volume "
           u"parcial, e só a face interna o cruzamento do limiar",
           u"curva do canal seguem a borda medida pelo volume parcial" in sup
           and u"face interna da peça segue o ponto" in sup
           and u"face interna da peça e a distância" not in sup, sup[:200])
    checar(u"(isca) a janela saiu do «?» da distância, que não fala mais dela",
           u"janela" not in u" ".join(A.AJUDA["distancia"]))
    mat = u" ".join(A.AJUDA["material"])
    checar(u"o «?» do material traz as referências (Bellis 2021, tabela 2; "
           u"Ricotti 2016)", u"Bellis 2021 (tabela 2)" in mat
           and u"Ricotti 2016" in mat and A.MATERIAL in mat)
    ent = u" ".join(A.AJUDA["entrada"])
    checar(u"o «?» da entrada vale nos dois trajetos e diz que a ficha conta "
           u"as distâncias da face escolhida",
           u"trajeto aberto" in ent and u"conta as distâncias" in ent
           and u"Só no fundo cego" not in ent, ent[:100])
    checar(u"o do trajeto diz por que o fundo cego tem alerta",
           u"nenhum dos seis artigos" in u" ".join(A.AJUDA["trajeto"]))
    dois = (u"10.5114/jcb.2024.137357", u"10.5114/jcb.2021.108602",
            u"10.5114/jcb.2022.114353", u"10.1016/j.ejmp.2016.08.016",
            u"10.1016/j.brachy.2019.05.006", u"10.1016/j.brachy.2016.11.003")
    refs = u" ".join(A.REFERENCIAS)
    checar(u"as seis referências, com o DOI tirado do PDF",
           len(A.REFERENCIAS) == 6 and all(d in refs for d in dois))
    pesq = u" ".join(A.PESQUISA_DE_CURVATURA)
    checar(u"o que ficou fora não entra na curvatura da ficha (o número do "
           u"VariSource iX e o relatório que só apareceu em trecho de busca)",
           u"VariSource" not in pesq and u"NÃO conferid" not in pesq
           and u"trecho de busca" not in pesq, pesq[-120:])
    checar(u"a curvatura cita as conferidas, com o DOI (Laan, Licher, Stern "
           u"e Liu)", all(x in pesq for x in (
               u"10.1186/s41205-019-0047-x", u"10.1007/s00066-025-02372-5",
               u"10.1120/jacmp.v11i4.3158")))
    fonte = io.open(_componentes.fonte("app/radai_bolus_aplicador.py"),
                    encoding="utf-8").read()
    import radai_bolus_screen as T
    pagina = T.pagina()
    fora = [n for n in FORA_DA_BIBLIOGRAFIA if n in fonte or n in pagina]
    checar(u"o que ficou fora da bibliografia não é citado no código nem na "
           u"tela", not fora, fora)
    checar(u"(isca) a mesma busca acha um nome que está lá",
           u"Laan" in fonte and u"Laan" in pagina)


def teste_parametros():
    secao(u"os parâmetros: o piso efetivo, e o que bloqueia antes da geometria")
    P = A.conferir_parametros({})
    checar(u"padrão: piso 17 mm (afterloader não informado, maior que o 6F)",
           P["piso_mm"] == 17.0 and P["folga_mm"] == 1.0, P["piso_mm"])
    for al, ca, piso in (("microselectron_digital", "6f", 15.0),
                         ("microselectron_digital", "proguide", 35.0),
                         ("flexitron", "6f", 17.0), ("bravos", "6f", 15.0),
                         ("gammamed_ix", "outro", 35.0)):
        P = A.conferir_parametros({"afterloader": al, "cateter": ca})
        checar(u"%s + %s: piso %d mm (o maior dos dois)" % (al, ca, piso),
               P["piso_mm"] == piso, P["piso_mm"])
    e = recusa(A.conferir_parametros, {"canal_mm": 1.9})
    checar(u"canal de 1,9 mm com o 6F: BLOQUEIA (mais estreito que o cateter)",
           isinstance(e, A.Bloqueio) and e.detalhe.get("motivo")
           == "canal_estreito" and e.campo == "canal_mm", e)
    e = recusa(A.conferir_parametros, {"corpo_mm": 50})
    checar(u"número fora da faixa: diz qual campo",
           isinstance(e, A.RecusaDoCampo) and e.campo == "corpo_mm", e)
    P = A.conferir_parametros({"canal_mm": 2.4})
    checar(u"folga de 0,4 mm: gera, com alerta da peça de calibração",
           any(u"calibração" in a for a in P["alertas"]), P["alertas"])
    P = A.conferir_parametros({"canal_mm": 2.6})
    checar(u"(isca) folga de 0,6 mm: sem o alerta",
           not any(u"calibração" in a for a in P["alertas"]))
    e = recusa(A.conferir_parametros, {"espacamento_mm": 5.0})
    checar(u"5 mm entre canais de 3 mm com funil: BLOQUEIA (se cruzariam)",
           isinstance(e, A.Bloqueio) and e.detalhe.get("motivo")
           == "canais_cruzam", e)
    checar(u"(isca) 7 mm passa", recusa(A.conferir_parametros,
                                        {"espacamento_mm": 7.0}) is None)
    e = recusa(A.conferir_parametros, {"distancia_mm": 3.0})
    checar(u"canal a 3 mm da pele, com funil: recusa (parede < 1 mm)",
           e is not None and u"parede" in str(e), e)
    e = recusa(A.conferir_parametros, {"corpo_mm": 7.0})
    checar(u"corpo de 7 mm com o canal a 5 mm: recusa (parede de fora)",
           e is not None and u"fino demais" in str(e), e)
    checar(u"afterloader desconhecido: recusa",
           recusa(A.conferir_parametros, {"afterloader": "xyz"}) is not None)
    checar(u"distância fora da faixa: recusa",
           recusa(A.conferir_parametros, {"distancia_mm": 40}) is not None)
    P = A.conferir_parametros({"trajeto": "cego"})
    checar(u"fundo cego: o alerta dos seis artigos",
           A.AVISO_FUNDO_CEGO in P["alertas"])
    P = A.conferir_parametros({"afterloader": "varisource_ix"})
    checar(u"VariSource iX: o alerta de número não conferido",
           any(u"NÃO conferido" in a for a in P["alertas"]))
    e = recusa(A.conferir_parametros, {"cateter": "outro",
                                       "diametro_externo_mm": 3.0,
                                       "canal_mm": 2.9})
    checar(u"cateter «outro» de 3,0 mm e canal de 2,9: BLOQUEIA",
           isinstance(e, A.Bloqueio), e)
    checar(u"«funil» em texto não liga o funil (só `true`)",
           A.conferir_parametros({"funil": "false"})["funil"] is False
           and A.conferir_parametros({})["funil"] is True)

    P = A.conferir_parametros({})
    checar(u"raio padrão: sem pedir, 35 mm e sem alerta",
           P["padrao_mm"] == 35.0 and P["padrao_sugerido_mm"] == 35.0
           and not P["alertas"], P["alertas"])
    P = A.conferir_parametros({"raio_padrao_mm": 50})
    checar(u"o físico sobe o padrão para 50 mm: vale, sem alerta",
           P["padrao_mm"] == 50.0 and not P["alertas"], P["padrao_mm"])
    checar(u"a faixa do campo começa em 35 mm (o padrão só sobe)",
           A.FAIXAS["raio_padrao_mm"] == (35.0, 100.0)
           and A.FAIXAS["raio_padrao_mm"][0] == A.RAIO_PADRAO_MM,
           A.FAIXAS["raio_padrao_mm"])
    e = recusa(A.conferir_parametros, {"raio_padrao_mm": 20})
    checar(u"(isca) 20 mm de padrão: RECUSA, diz o campo e explica (começa em "
           u"35, sempre amarela abaixo dele, e o piso não gera)",
           isinstance(e, A.RecusaDoCampo) and e.campo == "raio_padrao_mm"
           and u"começa em 35 mm e só sobe" in str(e)
           and u"sempre amarela" in str(e)
           and u"abaixo do piso de 17 mm" in str(e), e)
    e = recusa(A.conferir_parametros, {"raio_padrao_mm": 17})
    checar(u"17 mm, igual ao piso: também recusa (antes saía, com o trecho "
           u"de 17 a 35 mm verde)",
           isinstance(e, A.RecusaDoCampo) and e.campo == "raio_padrao_mm", e)
    e = recusa(A.conferir_parametros, {"raio_padrao_mm": "20"})
    checar(u"o 20 em texto também recusa",
           isinstance(e, A.RecusaDoCampo) and e.campo == "raio_padrao_mm", e)
    combinacoes = [(a["chave"], c["chave"]) for a in A.AFTERLOADERS
                   for c in A.CATETERES]
    baixo = [k for k in combinacoes if recusa(
        A.conferir_parametros, {"afterloader": k[0], "cateter": k[1],
                                "raio_padrao_mm": 34.9,
                                "diametro_externo_mm": 2.0}) is None]
    checar(u"34,9 mm recusa em todas as %d combinações de afterloader e "
           u"cateter" % len(combinacoes), not baixo, baixo)
    ok35 = [k for k in combinacoes if recusa(
        A.conferir_parametros, {"afterloader": k[0], "cateter": k[1],
                                "raio_padrao_mm": 35,
                                "diametro_externo_mm": 2.0}) is not None]
    checar(u"(isca) 35 mm vale em todas elas, inclusive com o ProGuide (piso "
           u"35)", not ok35, ok35)
    e = recusa(A.conferir_parametros, {"raio_padrao_mm": 200})
    checar(u"200 mm: fora da faixa, e diz o campo",
           isinstance(e, A.RecusaDoCampo) and e.campo == "raio_padrao_mm", e)
    velhos = A.CATETERES
    try:
        A.CATETERES = velhos + ({"chave": "zz40", "nome": u"cateter de teste",
                                 "diametro_mm": 2.0, "piso_mm": 40.0,
                                 "curta": u"teste", "fonte": u"teste"},)
        e38 = recusa(A.conferir_parametros, {"cateter": "zz40",
                                             "raio_padrao_mm": 38})
        e40 = recusa(A.conferir_parametros, {"cateter": "zz40",
                                             "raio_padrao_mm": 40})
    finally:
        A.CATETERES = velhos
    checar(u"cateter de piso acima de 35 mm: o padrão começa no piso (38 "
           u"recusa, 40 vale)",
           isinstance(e38, A.RecusaDoCampo) and e38.campo == "raio_padrao_mm"
           and u"abaixo do piso de 40 mm" in str(e38) and e40 is None,
           (e38, e40))
    checar(u"o limiar do amarelo nunca fica abaixo de 35 mm",
           A.limiar_amarelo(20) == 35.0 and A.limiar_amarelo(50) == 50.0
           and A.limiar_amarelo(None) == 35.0
           and A.limiar_amarelo(float("nan")) == 35.0)
    checar(u"curva de 30 mm com padrão forjado em 20: amarela; reta e 40 mm "
           u"com 35: verdes",
           A.curva_e_amarela(30.0, 20.0)
           and not A.curva_e_amarela(float("inf"), 20.0)
           and not A.curva_e_amarela(40.0, 35.0)
           and A.curva_e_amarela(40.0, 50.0))


def teste_curvatura():
    secao(u"a curvatura: medida na linha reamostrada, e não nos vértices")
    t = np.linspace(0, math.pi / 2, 400)
    circ = np.stack([20 * np.cos(t), 20 * np.sin(t), np.zeros_like(t)], 1)
    R, s, q = A.raios_de_curvatura(circ)
    fin = R[np.isfinite(R)]
    checar(u"arco de 20 mm: raio medido a 1%% (%.3f a %.3f)"
           % (fin.min(), fin.max()),
           abs(fin.min() - 20) < 0.2 and abs(fin.max() - 20) < 0.2)
    checar(u"reamostrada a 0,5 mm (≤ 1 mm)",
           np.allclose(np.diff(s), A.PASSO_DA_LINHA_MM)
           and A.PASSO_DA_LINHA_MM <= 1.0 and A.VIZINHO_DA_CURVATURA_MM <= 1.0)
    reta = np.stack([np.linspace(0, 50, 200), np.zeros(200), np.zeros(200)], 1)
    checar(u"reta: sem curva",
           not np.isfinite(A.raios_de_curvatura(reta)[0]).any()
           or A.raios_de_curvatura(reta)[0].min() > 1e6)
    ang = math.radians(30)
    quina = np.array([[-10.0, 0, 0], [0, 0, 0],
                      [10 * math.cos(ang), 10 * math.sin(ang), 0]])
    R2 = A.raios_de_curvatura(quina)[0]
    a, b, c = quina
    so_vertices = (np.linalg.norm(b - a) * np.linalg.norm(c - b)
                   * np.linalg.norm(a - c)
                   / (2 * np.linalg.norm(np.cross(b - a, c - a))))
    checar(u"quina de 30° entre vértices a 10 mm: a linha reamostrada acha "
           u"%.1f mm" % R2.min(), R2.min() < 5.0)
    checar(u"(isca) medida só nos vértices ela daria %.1f mm e passaria do "
           u"piso de 13" % so_vertices, so_vertices > 13.0)
    checar(u"a maior sequência de falhas do refino da pele",
           A._maior_sequencia([0, 1, 1, 0, 1, 1, 1, 0]) == 3
           and A._maior_sequencia([0, 0]) == 0)
    tr = A.trechos_abaixo(np.array([50, 40, 30, 20, 30, 50, 34, 60.0]),
                          np.arange(8) * 0.5, 35)
    checar(u"os trechos abaixo de 35 mm, contados da entrada",
           tr == [(1.0, 2.0), (3.0, 3.0)], tr)
    x = np.linspace(0, 40, 161)
    y = 0.7 * x + 3.0
    checar(u"a suavização preserva uma reta até nas pontas",
           np.abs(A._suavizar(y, 20.0) - y).max() < 1e-9)
    from scipy import ndimage
    ruim = ndimage.gaussian_filter1d(y, 20.0, mode="nearest")
    pts = np.stack([x, ruim, np.zeros_like(x)], 1)
    checar(u"(isca) a suavização ingênua dobra a reta nas pontas (R %.0f mm)"
           % A.raios_de_curvatura(pts)[0].min(),
           A.raios_de_curvatura(pts)[0].min() < 200)


def teste_pele_subvoxel(s):
    secao(u"a pele medida no cruzamento do HU, e não na máscara voxelizada")
    cx = caixa(s, (-30, -105, -30), (30, -60, 30))
    cxn = B.normalizar_caixa(s, cx)
    h, off, forma = B._grade(s, cxn, 12.0)
    J, corpo, lo, hi, d, _a, _av = B.campos_da_pele(s, cxn, h, off, forma,
                                                    "ant")
    def raios(pts):
        lps = s.quadro_para_lps(off[None, :] + pts)
        perto = np.abs(lps[:, 2]) < 25
        r = np.sqrt(lps[perto, 0] ** 2 + lps[perto, 1] ** 2)
        return r[lps[perto, 1] < -60]

    rr = raios(A.pontos_da_pele(J, corpo, h, s, off))
    checar(u"%d pontos da pele na frente, a %.3f ± %.3f mm do eixo (80 mm): "
           u"a borda sai do volume parcial dos voxels do cruzamento"
           % (len(rr), rr.mean(), rr.std()),
           len(rr) > 1000 and abs(rr.mean() - 80.0) < 0.05
           and rr.std() < 0.05, (len(rr), rr.mean(), rr.std()))
    linear = raios(A.pontos_da_pele(J, corpo, h))
    checar(u"(isca) o cruzamento linear do limiar, o método de antes, põe a "
           u"pele %.2f mm para dentro e espalha %.3f mm"
           % (80.0 - linear.mean(), linear.std()),
           80.0 - linear.mean() > 0.15 and linear.std() > 2 * rr.std(),
           (linear.mean(), linear.std()))
    from scipy import ndimage
    borda = corpo & ~ndimage.binary_erosion(corpo)
    zz, yy, xx = np.nonzero(borda)
    lb = s.quadro_para_lps(off[None, :] + np.stack([xx, yy, zz], 1) * h)
    ok = (np.abs(lb[:, 2]) < 25) & (lb[:, 1] < -60)
    rb = np.sqrt(lb[ok, 0] ** 2 + lb[ok, 1] ** 2)
    checar(u"(isca) a borda da máscara voxelizada espalha %.3f mm — mais que "
           u"o dobro" % rb.std(), rb.std() > 2 * rr.std())
    larg = A.larguras_da_transicao(np.array([[0.0, 0.0, 1.0],
                                             [0.0, 0.8, 0.6]]),
                                   np.array([1.0, 1.0, 3.0]))
    checar(u"a largura da transição em amostras: 1 com a pele de frente para "
           u"o eixo; o corte de 3 mm é o eixo bom da pele inclinada "
           u"(%.2f contra %.2f)" % (larg[1, 2], larg[1, 1]),
           abs(larg[0, 2] - 1.0) < 1e-9 and np.isinf(larg[0, 0])
           and larg[1, 2] < larg[1, 1], larg)


def teste_gerar_cilindro(s):
    secao(u"no cilindro de 80 mm: canais retos e curvos, medidos de volta")
    cx = caixa(s, (-30, -105, -30), (30, -60, 30))
    t0 = time.time()
    r = A.gerar(s, cx, {"eixo": "cc", "direcao": "ant"})
    print(u"         · craniocaudal: %.1f s, grade %.2f mm, %d canais, %d "
          u"triângulos" % (time.time() - t0, r["grade_mm"], len(r["canais"]),
                           r["malha"]["triangulos"]))
    checar(u"seis canais na caixa de 60 mm (10 mm entre eles)",
           len(r["canais"]) == 6, len(r["canais"]))
    vs = sorted(c["v_mm"] for c in r["canais"])
    checar(u"espaçados de 10 mm", np.allclose(np.diff(vs), 10.0))
    checar(u"retos (raio ≥ 1 m) e verdes",
           r["raio_min_mm"] >= A.RAIO_RETO_MM and r["classe"] == "verde",
           r["raio_min_mm"])
    checar(u"o eixo do canal a 5 mm da pele (%.2f a %.2f)"
           % (r["pele_min_mm"], r["pele_max_mm"]),
           abs(r["pele_min_mm"] - 5) < 0.15 and abs(r["pele_max_mm"] - 5) < 0.15)
    dm = [c["diametro_medido_mm"] for c in r["canais"]]
    checar(u"o diâmetro medido na malha bate com os 3,0 mm (%.3f a %.3f)"
           % (min(dm), max(dm)), 2.9 <= min(dm) and max(dm) <= 3.15, dm)
    bocas = [b for c in r["canais"] for b in c["boca_medida_mm"]]
    checar(u"a boca afunila nas duas pontas (%.2f mm contra %.2f no meio)"
           % (min(bocas), max(dm)), len(bocas) == 12
           and min(bocas) > max(dm) + 1.0, bocas)
    m = r["malha"]
    checar(u"malha fechada, para fora, uma peça, volta exata (DSC %.5f)"
           % r["dsc_ida_volta"], m["fechada"] and m["volume_mm3"] > 0
           and r["pecas"] == 1 and r["dsc_ida_volta"] >= 0.9999
           and r["colunas_impares"] == 0, (m, r["pecas"]))
    checar(u"o cabeçalho é o do aplicador, rascunho não aprovado",
           r["stl"][:80] == A.CABECALHO_STL.ljust(80, b" ")
           and B.cabecalho_seguro(r["stl"][:80]) and len(A.CABECALHO_STL) <= 80)
    checar(u"nada da série no STL", b"ZZSENTINELA" not in r["stl"])
    t = tri_lps(r["stl"])
    lin = linhas_lps(s, r)
    meio = [l[len(l) // 2] for l in lin]
    entre = 0.5 * (meio[0] + meio[1])
    pele = np.array([[0.0, -math.sqrt(80 ** 2 - 0.0), 0.0]])
    dentro = B.dentro_da_malha(t, np.array(
        meio[:2] + [entre, pele[0] + [0, -1.5, 0], pele[0] + [0, -9.0, 0],
                    pele[0] + [0, -11.0, 0], pele[0] + [0, 2.0, 0]]))
    checar(u"o eixo do canal está FORA do material (o canal é oco)",
           not dentro[0] and not dentro[1], dentro[:2])
    checar(u"entre dois canais, na mesma profundidade, é material",
           dentro[2], dentro[2])
    checar(u"a 1,5 mm e a 9 mm da pele é material; a 11 mm, não; dentro do "
           u"corpo, não", dentro[3] and dentro[4] and not dentro[5]
           and not dentro[6], dentro[3:])
    ini = [l[0] for l in lin]
    fora = B.dentro_da_malha(t, np.array(ini))
    checar(u"o canal sai nas duas faces da caixa (a ponta está fora)",
           not fora.any(), fora)

    t0 = time.time()
    r2 = A.gerar(s, cx, {"eixo": "ll", "direcao": "ant"})
    print(u"         · laterolateral: %.1f s, raio mínimo %.1f mm"
          % (time.time() - t0, r2["raio_min_mm"]))
    esperado = 80.0 - 0.2 + 5.0
    checar(u"sobre o cilindro, o canal curva com ~%.0f mm (medido %.1f; a "
           u"medida tem ±15%%)" % (esperado, r2["raio_min_mm"]),
           0.85 * esperado <= r2["raio_min_mm"] <= 1.15 * esperado
           and r2["classe"] == "verde", r2["raio_min_mm"])
    r3 = A.gerar(s, cx, {"eixo": "ll", "direcao": "ant",
                         "raio_padrao_mm": 100})
    checar(u"o mesmo canal com o padrão subido para 100 mm: AMARELO, com os "
           u"trechos contados (a curva amarela segue o campo)",
           r3["classe"] == "amarelo" and r3["padrao_mm"] == 100.0
           and all(c["trechos_amarelos"] for c in r3["canais"]),
           (r3["classe"], r3["padrao_mm"]))
    lin2 = linhas_lps(s, r2)
    rr = np.concatenate([np.sqrt(l[:, 0] ** 2 + l[:, 1] ** 2) for l in lin2])
    checar(u"e o canal fica a 5 mm da pele em todo o arco (%.2f a %.2f do "
           u"eixo)" % (rr.min(), rr.max()), rr.min() > 84.2 and rr.max() < 85.2)
    return r


def teste_curva_amarela_e_piso():
    secao(u"a curva amarela e o piso que bloqueia (cilindro de 20 mm)")
    s = B.abrir(cilindro(R=20.0, L=40.0, esp=(0.5, 0.5, 1.0),
                         meia=(40.0, 40.0, 50.0)), "CT")
    cx = caixa(s, (-14, -42, -16), (14, -14, 16))
    r = A.gerar(s, cx, {"eixo": "ll", "direcao": "ant"})
    print(u"         · raio mínimo %.1f mm, grade %.2f mm, %d canais"
          % (r["raio_min_mm"], r["grade_mm"], len(r["canais"])))
    checar(u"sem afterloader informado (piso 17): gera, AMARELA (%.1f mm)"
           % r["raio_min_mm"], r["classe"] == "amarelo"
           and 21 <= r["raio_min_mm"] <= 30, r["raio_min_mm"])
    checar(u"o alerta amarelo vem primeiro, com o canal e o piso",
           r["avisos"][0].startswith(u"Curva amarela"), r["avisos"][:1])
    checar(u"e as quatro exigências da curva entram na ficha",
           all(e in r["exigencias"] for e in A.EXIGENCIAS_DA_CURVA)
           and len(A.EXIGENCIAS_DA_CURVA) == 4)
    checar(u"os trechos abaixo de 35 mm estão contados",
           all(c["trechos_amarelos"] for c in r["canais"]))
    e = recusa(A.gerar, s, cx, {"eixo": "ll", "direcao": "ant",
                                "cateter": "proguide",
                                "afterloader": "microselectron_digital"})
    checar(u"com ProGuide e obturador (piso 35): NÃO gera",
           isinstance(e, A.Bloqueio) and e.detalhe.get("motivo")
           == "raio_abaixo_do_piso", e)
    checar(u"e propõe as quatro alternativas",
           e is not None and len(e.detalhe.get("propostas") or []) == 4
           and u"Proponho" in str(e) and u"corpo mais espesso" in str(e))
    r6 = A.gerar(s, cx, {"eixo": "ll", "direcao": "ant",
                         "afterloader": "microselectron_digital"})
    checar(u"(isca) a mesma curva com microSelectron e 6F (piso 15): gera",
           r6["classe"] == "amarelo" and r6["piso_mm"] == 15.0)
    s2 = B.abrir(cilindro(R=8.0, L=40.0, esp=(0.5, 0.5, 1.0),
                          meia=(30.0, 30.0, 50.0)), "CT")
    cx2 = caixa(s2, (-6, -26, -12), (6, -2, 12))
    e2 = recusa(A.gerar, s2, cx2, {"eixo": "ll", "direcao": "ant",
                                   "afterloader": "microselectron_digital"})
    checar(u"cilindro de 8 mm (canal com ~13 mm) e 6F: NÃO gera (%s)"
           % (e2.detalhe.get("raio_min_mm") if isinstance(e2, A.Bloqueio)
              else e2), isinstance(e2, A.Bloqueio)
           and e2.detalhe.get("motivo") == "raio_abaixo_do_piso", e2)
    return s, cx, r


def _canal_em_l(entrada, trajeto="aberto"):
    reta = np.stack([np.arange(0.0, 40.0, 0.25), np.zeros(160),
                     np.zeros(160)], 1)
    phi = np.linspace(0.0, 0.8, 81)
    arco = np.stack([40.0 + 25.0 * np.sin(phi), 25.0 - 25.0 * np.cos(phi),
                     np.zeros_like(phi)], 1)
    linha = np.concatenate([reta, arco])
    P = {"raio_mm": 1.5, "raio_funil_mm": 2.5, "trajeto": trajeto,
         "entrada": entrada, "funil": True, "padrao_mm": 35.0}
    c = A._montar_canal({"linha": linha}, P, 0, 0.0, float(linha[-1, 0]),
                        0.5)
    A._medir_curvas([c], P)
    return c


def teste_face_de_entrada(s, cx):
    secao(u"a face de entrada: nomeada no aberto e no cego, e as distâncias "
          u"contam dela")
    ini, fim = _canal_em_l("inicio"), _canal_em_l("fim")
    L = ini["comprimento_mm"]
    ti, tf = ini["trechos_amarelos"], fim["trechos_amarelos"]
    checar(u"canal reto e depois curvo (raio 25 mm): pela face do início, a "
           u"curva começa a ~40 mm (%s)" % ti,
           len(ti) == 1 and 38.0 <= ti[0][0] <= 42.0 and ti[0][1] > 50.0, ti)
    checar(u"no trajeto ABERTO com entrada pelo fim, a mesma curva fica no "
           u"começo do canal (%s; comprimento %.1f mm)" % (tf, L),
           len(tf) == 1 and tf[0][0] <= 2.0
           and abs(tf[0][1] - (L - ti[0][0])) <= 2.0, tf)
    checar(u"e o raio mínimo também é contado da face escolhida (no arco: "
           u"%.1f mm do início, %.1f mm do fim)"
           % (ini["raio_min_em_mm"], fim["raio_min_em_mm"]),
           ini["raio_min_em_mm"] >= 38.0
           and fim["raio_min_em_mm"] <= L - 38.0,
           (ini["raio_min_em_mm"], fim["raio_min_em_mm"], L))
    checar(u"os nomes das faces: no eixo laterolateral, direita e esquerda; "
           u"no craniocaudal, inferior e superior",
           A.face_de_entrada(0, "inicio") == u"direita"
           and A.face_de_entrada(0, "fim") == u"esquerda"
           and A.face_de_entrada(2, "inicio") == u"inferior"
           and A.face_de_entrada(2, "fim") == u"superior")
    checar(u"os trechos são arredondados para fora (12,6–19,4 vira 12–20)",
           A.trechos_para_fora([(12.6, 19.4)], 60.0) == [(12.0, 20.0)])
    checar(u"(isca) o arredondamento comum daria 13–19 e encolheria o trecho",
           (round(12.6), round(19.4)) == (13, 19))

    def res_de(c, entrada):
        return {"eixo_espacamento": 1, "eixo_canal": 0, "padrao_mm": 35.0,
                "classe": "amarelo", "face_entrada": A.face_de_entrada(
                    0, entrada),
                "parametros": {"entrada": entrada},
                "canais": [{"n": 1, "comprimento_mm": c["comprimento_mm"],
                            "raio_min_mm": c["raio_min_mm"],
                            "raio_min_em_mm": c["raio_min_em_mm"],
                            "trechos_amarelos": c["trechos_amarelos"],
                            "pele_min_mm": 5.0, "pele_max_mm": 5.0,
                            "diametro_medido_mm": 3.0},
                           {"n": 2, "comprimento_mm": c["comprimento_mm"],
                            "raio_min_mm": float("inf"),
                            "raio_min_em_mm": None, "trechos_amarelos": [],
                            "pele_min_mm": 5.0, "pele_max_mm": 5.0,
                            "diametro_medido_mm": 3.0}]}

    txt = u"\n".join(A.linhas_dos_canais(res_de(fim, "fim")))
    a, b = A.trechos_para_fora(tf, fim["comprimento_mm"])[0]
    checar(u"a ficha nomeia a face de entrada de cada canal e conta dela",
           u"contam da face esquerda" in txt
           and txt.count(u"entra pela face esquerda") == 2
           and (u"a %s mm da face esquerda" % A._mm(fim["raio_min_em_mm"], 0))
           in txt, txt[:300])
    checar(u"e mostra o trecho amarelo do canal com o início e o fim (%s a "
           u"%s mm)" % (A._mm(a, 0), A._mm(b, 0)),
           (u"começa a %s mm e termina a %s mm da face esquerda"
            % (A._mm(a, 0), A._mm(b, 0))) in txt, txt[-300:])
    checar(u"o canal sem curva amarela também é dito",
           u"Canal 2: nenhum trecho abaixo de 35 mm." in txt)
    isca = u"\n".join(A.linhas_dos_canais(res_de(ini, "inicio")))
    checar(u"(isca) pela face do início, a ficha diz direita, e não esquerda",
           u"face direita" in isca and u"face esquerda" not in isca)

    r = A.gerar(s, cx, {"eixo": "ll", "direcao": "ant", "entrada": "fim"})
    checar(u"no aplicador ABERTO com entrada pelo fim, o resultado nomeia a "
           u"face (%s)" % r.get("face_entrada"),
           r["face_entrada"] == u"esquerda"
           and r["parametros"]["trajeto"] == "aberto", r.get("face_entrada"))
    par = dict(A.linhas_de_parametros(r))
    checar(u"a linha de parâmetros diz a face de entrada também no aberto",
           par.get(u"Face de entrada do cateter (as distâncias contam "
                   u"dela)") == u"esquerda", par)
    checar(u"e o alerta amarelo diz de qual face conta o raio mínimo",
           r["classe"] == "amarelo" and u"da face esquerda, a de entrada"
           in r["avisos"][0], r["avisos"][:1])
    ficha = A.ficha(r, u"x.stl")
    checar(u"a ficha traz a face, os trechos de cada canal e a regra da "
           u"parada", u"Trechos de curva amarela, contados da face esquerda"
           in ficha and ficha.count(u"curva amarela (raio abaixo de 35 mm)")
           == sum(1 for c in r["canais"] if c["trechos_amarelos"])
           and u"Nenhuma parada ativa nesses trechos" in ficha)
    e20 = recusa(A.gerar, s, cx, {"eixo": "ll", "direcao": "ant",
                                  "raio_padrao_mm": 20})
    checar(u"a mesma curva (%.1f mm) com o padrão pedido em 20 mm: não gera "
           u"verde, recusa o campo" % r["raio_min_mm"],
           isinstance(e20, A.RecusaDoCampo) and e20.campo == "raio_padrao_mm"
           and u"começa em 35 mm" in str(e20), e20)
    checar(u"e no mínimo do campo (35 mm) ela sai AMARELA, com as quatro "
           u"exigências na ficha",
           r["padrao_mm"] == 35.0 and r["raio_min_mm"] < 35.0
           and all(e in r["exigencias"] for e in A.EXIGENCIAS_DA_CURVA)
           and all(e in ficha for e in A.EXIGENCIAS_DA_CURVA),
           (r["padrao_mm"], r["raio_min_mm"]))
    r50 = A.gerar(s, cx, {"eixo": "ll", "direcao": "ant", "entrada": "fim",
                          "raio_padrao_mm": 50})
    f50 = A.ficha(r50, u"x.stl")
    checar(u"com o padrão subido para 50 mm, a ficha diz o escolhido e o "
           u"sugerido, e os trechos contam abaixo de 50 mm",
           u"50,0 mm (o sugerido é 35 mm)" in f50
           and u"curva amarela (raio abaixo de 50 mm)" in f50, f50[:200])

    velho = A.conferir_parametros

    def forjado(p=None):
        q = dict(p or {})
        q.pop("raio_padrao_mm", None)
        P = velho(q)
        P["padrao_mm"] = 20.0
        return P

    def gerar_forjado(limiar=None):
        lim = A.limiar_amarelo
        A.conferir_parametros = forjado
        if limiar is not None:
            A.limiar_amarelo = limiar
        try:
            return A.gerar(s, cx, {"eixo": "ll", "direcao": "ant",
                                   "entrada": "fim"})
        finally:
            A.conferir_parametros = velho
            A.limiar_amarelo = lim

    rf = gerar_forjado()
    txt_f = u"\n".join(A.linhas_dos_canais(rf))
    checar(u"padrão forjado em 20 mm por dentro, sem passar pelo campo: a "
           u"curva de %.1f mm continua AMARELA, com as quatro exigências, os "
           u"trechos abaixo de 35 mm e o segundo ato" % rf["raio_min_mm"],
           rf["classe"] == "amarelo"
           and all(e in rf["exigencias"] for e in A.EXIGENCIAS_DA_CURVA)
           and all(c["trechos_amarelos"] for c in rf["canais"]
                   if c["raio_min_mm"] < 35.0)
           and u"curva amarela (raio abaixo de 35 mm)" in txt_f
           and recusa(A.conferir_ato, rf, True, A.FRASE_DO_ATO) is not None,
           (rf["classe"], txt_f[-200:]))
    falso = dict(rf, classe="verde")
    checar(u"e o resultado forjado em verde com a curva abaixo de 35 mm ainda "
           u"exige o segundo ato",
           recusa(A.conferir_ato, falso, True, A.FRASE_DO_ATO) is not None)
    rv = gerar_forjado(limiar=lambda p: float(p))
    checar(u"(isca) com o limiar antigo (o padrão recebido, sem o chão de 35 "
           u"mm), a mesma curva sairia verde e sem as exigências",
           rv["classe"] == "verde"
           and not any(e in rv["exigencias"] for e in A.EXIGENCIAS_DA_CURVA),
           rv["classe"])


def teste_cruzamento():
    secao(u"canais que se cruzam: a conferência entre todos os pares")
    linha = np.stack([np.linspace(0, 40, 161), np.zeros(161), np.zeros(161)], 1)

    def canal(l):
        return {"toda": l, "na_caixa": np.ones(len(l), bool),
                "raio_corte": np.full(len(l), 1.5)}

    par = [canal(linha), canal(linha + [0, 10.0, 0])]
    checar(u"paralelos a 10 mm, raio 1,5: parede de 7 mm",
           abs(A._menor_folga_entre_canais(par) - 7.0) < 1e-6)
    t = np.linspace(-20, 20, 161)
    cruz = [canal(linha - [20, 0, 0]),
            canal(np.stack([np.zeros(161), t, np.zeros(161)], 1))]
    checar(u"cruzados: parede negativa (%.1f mm)"
           % A._menor_folga_entre_canais(cruz),
           A._menor_folga_entre_canais(cruz) < 0)


def teste_fundo_cego(s):
    secao(u"fundo cego: a entrada aberta, o fundo fechado, e o alerta")
    cx = caixa(s, (-15, -105, -30), (15, -60, 30))
    r = A.gerar(s, cx, {"eixo": "cc", "direcao": "ant", "trajeto": "cego",
                        "entrada": "inicio"})
    checar(u"o alerta do fundo cego está nos avisos",
           A.AVISO_FUNDO_CEGO in r["avisos"])
    checar(u"uma boca só, na entrada",
           all(len(c["boca_medida_mm"]) == 1 for c in r["canais"]))
    t = tri_lps(r["stl"])
    lin = linhas_lps(s, r)
    entrada, fundo = lin[0][0], lin[0][-1]
    alem = fundo + np.array([0, 0, A.FUNDO_CEGO_PAREDE_MM / 2.0
                             + r["parametros"]["raio_mm"]])
    d = B.dentro_da_malha(t, np.array([entrada, alem]))
    checar(u"a entrada (inferior) é oca, e além do fundo há parede",
           not d[0] and d[1], d)
    checar(u"a malha fecha", r["malha"]["fechada"] and r["pecas"] == 1)
    par = dict(A.linhas_de_parametros(r))
    checar(u"no cego, a face de entrada é nomeada do mesmo jeito (inferior)",
           r["face_entrada"] == u"inferior" and par.get(
               u"Face de entrada do cateter (as distâncias contam dela)")
           == u"inferior" and u"entra pela face inferior" in u" ".join(
               A.linhas_dos_canais(r)), par)
    checar(u"o nome diz que é cego",
           u"_blind_" in A.nome_do_aplicador(r, u"0123456789abcdef"))


def teste_descartados(s):
    secao(u"canal sem pele embaixo fica fora, e diz por quê")
    cx = caixa(s, (40, -105, -20), (100, -20, 20))
    r = A.gerar(s, cx, {"eixo": "cc", "direcao": "ant"})
    checar(u"%d canais ficaram, %d foram descartados, com o motivo"
           % (len(r["canais"]), len(r["descartados"])),
           len(r["canais"]) >= 1 and len(r["descartados"]) >= 1
           and any(u"não coube" in a for a in r["avisos"]),
           (len(r["canais"]), r["descartados"]))
    fora = [a for a in r["avisos"] if u"não coube" in a]
    checar(u"o aviso do canal descartado diz a causa separada (falta pele, "
           u"e de que lado), e não as três numa frase só",
           fora and all(u"falta pele" in a and u"do lado" in a
                        and MOTIVO_ANTIGO not in a for a in fora), fora[:1])
    longe = caixa(s, (90, -105, -20), (105, -95, 20))
    e = recusa(A.gerar, s, longe, {"eixo": "cc", "direcao": "ant"})
    checar(u"caixa longe da pele: recusa dizendo por quê",
           e is not None and (u"sobrou" in str(e) or u"pele" in str(e)), e)
    e = recusa(A.gerar, s, caixa(s, (-30, -105, -30), (30, -60, 30)),
               {"eixo": "ap", "direcao": "ant"})
    checar(u"canais na direção da colocação: recusa",
           e is not None and u"direção" in str(e), e)


def domo_rampa(R=65.0, esp=(1.2, 1.2, 2.0)):
    xs = np.arange(-200.0, -10.0 + 1e-6, esp[0])
    ys = np.arange(-90.0, 90.0 + 1e-6, esp[1])
    zs = np.arange(-110.0, 50.0 + 1e-6, esp[2])
    Z, Y, X = np.meshgrid(zs, ys, xs, indexing="ij")
    xc = np.clip(X, -170.0, 170.0)
    sd = np.sqrt((X - xc) ** 2 + Y ** 2 + (Z + R) ** 2) - R
    sd = np.minimum(sd, np.maximum(np.abs(Y) - R, Z + R))
    frac = np.clip(0.5 - sd / min(esp), 0.0, 1.0)
    img = sitk.GetImageFromArray((-1000.0 + 1040.0 * frac).astype(np.int16))
    img.SetSpacing(tuple(float(e) for e in esp))
    img.SetOrigin((float(xs[0]), float(ys[0]), float(zs[0])))
    return img


def domo(R=65.0, esp=(1.0, 1.0, 2.0), passo=0.05):
    xs = np.arange(-200.0, -10.0 + 1e-6, esp[0])
    ys = np.arange(-90.0, 90.0 + 1e-6, esp[1])
    zs = np.arange(-110.0, 50.0 + 1e-6, esp[2])
    Z, Y = np.meshgrid(zs, ys, indexing="ij")
    ny = max(3, int(round(esp[1] / passo)) | 1)
    nz = max(3, int(round(esp[2] / passo)) | 1)
    frac = np.zeros(Z.shape)
    for dz in ((np.arange(nz) + 0.5) / nz - 0.5) * esp[2]:
        for dy in ((np.arange(ny) + 0.5) / ny - 0.5) * esp[1]:
            yy, zz = Y + dy, Z + dz
            sd = np.minimum(np.sqrt(yy ** 2 + (zz + R) ** 2) - R,
                            np.maximum(np.abs(yy) - R, zz + R))
            frac += sd < 0
    frac /= ny * nz
    vol = np.empty((len(zs), len(ys), len(xs)), dtype=np.int16)
    vol[...] = np.round(-1000.0 + 1040.0 * frac).astype(np.int16)[:, :, None]
    vol[:, :, xs < -170.0] = -1000
    img = sitk.GetImageFromArray(vol)
    img.SetSpacing(tuple(float(e) for e in esp))
    img.SetOrigin((float(xs[0]), float(ys[0]), float(zs[0])))
    return img


def teste_borda_por_volume_parcial():
    secao(u"a borda pelo volume parcial: a fase do voxel não mexe na pele")
    esp = np.array([1.0, 1.0, 3.0])
    zs = np.arange(20) * esp[2]
    erro_vp, erro_lin = [], []
    for e in np.linspace(30.0, 33.0, 31):
        occ = np.clip((e - (zs - esp[2] / 2.0)) / esp[2], 0.0, 1.0)
        col = np.round(-1000.0 + 1040.0 * occ)
        hu = np.empty((len(zs), 3, 3), dtype=np.int16)
        hu[...] = col.astype(np.int16)[:, None, None]
        j = int(np.nonzero((col[:-1] >= B.LIMIAR_HU)
                           & (col[1:] < B.LIMIAR_HU))[0][0])
        z_lin = zs[j] + (col[j] - B.LIMIAR_HU) / (col[j] - col[j + 1]) * esp[2]
        novo, ok = A.borda_por_volume_parcial(
            hu, esp, np.zeros(3), np.array([[1.0, 1.0, z_lin]]), 2, -1,
            np.array([1.0]))
        erro_vp.append(novo[0] - e if ok[0] else np.inf)
        erro_lin.append(z_lin - e)
    erro_vp, erro_lin = np.array(erro_vp), np.array(erro_lin)
    checar(u"corte de 3 mm, a borda em 31 fases do voxel: o volume parcial "
           u"acerta em todas (erro máximo %.3f mm)" % np.abs(erro_vp).max(),
           np.abs(erro_vp).max() < 0.01, erro_vp)
    checar(u"(isca) o cruzamento linear do limiar oscila %.2f mm de pico a "
           u"pico com a fase, o tamanho do erro que apertava a curva"
           % (erro_lin.max() - erro_lin.min()),
           erro_lin.max() - erro_lin.min() > 0.4, erro_lin)
    occ = np.clip((31.4 - (zs - esp[2] / 2.0)) / esp[2], 0.0, 1.0)
    col = -1000.0 + 1040.0 * occ
    col[occ >= 1.0] = np.where(np.arange(int((occ >= 1.0).sum())) % 2, 40.0,
                               -300.0)
    hu = np.empty((len(zs), 3, 3), dtype=np.int16)
    hu[...] = np.round(col).astype(np.int16)[:, None, None]
    _novo, ok = A.borda_por_volume_parcial(
        hu, esp, np.zeros(3), np.array([[1.0, 1.0, 31.0]]), 2, -1,
        np.array([1.0]))
    checar(u"tecido que não é um platô sob a pele: a borda fica no "
           u"cruzamento linear, e não vai para longe", not ok[0], ok)


def teste_raio_no_domo():
    secao(u"o raio medido sobre um domo de 65 mm, com corte de 1, 2 e 3 mm")
    geometrico = 65.0 + A.DISTANCIA_PADRAO_MM
    par = {"eixo": "ap", "direcao": "sup",
           "afterloader": "microselectron_digital"}
    original = A.pontos_da_pele

    def so_linear(J, corpo, h, serie=None, off=None):
        return original(J, corpo, h)

    medidos, antigos = [], []
    for esp in ((1.0, 1.0, 1.0), (1.0, 1.0, 2.0), (1.0, 1.0, 3.0)):
        s = B.abrir(domo(esp=esp), "CT")
        cx = caixa(s, (-150.0, -35.0, -40.0), (-80.0, 35.0, 31.0))
        medidos.append(A.gerar(s, cx, par)["raio_min_mm"])
        A.pontos_da_pele = so_linear
        try:
            antigos.append(A.gerar(s, cx, par)["raio_min_mm"])
        finally:
            A.pontos_da_pele = original
        print(u"         · corte de %g mm: raio mínimo %.1f mm (com o "
              u"cruzamento linear de antes, %.1f), geométrico %.0f"
              % (esp[2], medidos[-1], antigos[-1], geometrico))
    checar(u"o erro cai para poucos por cento nos três cortes (%s mm contra "
           u"%.0f; até 5%% abaixo)" % (u", ".join(u"%.1f" % m for m in medidos),
                                      geometrico),
           all(m >= 0.95 * geometrico for m in medidos), medidos)
    checar(u"e continua do lado seguro: o raio medido nunca passa do "
           u"geométrico", all(m <= 1.01 * geometrico for m in medidos),
           medidos)
    checar(u"(isca) com o cruzamento linear de antes, o mesmo domo dava %s "
           u"mm: 9 a 30%% abaixo, pior no corte grosso"
           % u", ".join(u"%.1f" % m for m in antigos),
           all(m < 0.95 * geometrico for m in antigos)
           and antigos[2] < 0.8 * geometrico, antigos)
    s = B.abrir(domo_rampa(esp=(1.2, 1.2, 2.0)), "CT")
    r = A.gerar(s, caixa(s, (-150.0, -35.0, -40.0), (-80.0, 35.0, 31.0)), par)
    checar(u"borda mais fina que o corte (1,2 mm num corte de 2 mm, que a TC "
           u"não grava): o raio %.1f mm ainda só erra para o lado seguro"
           % r["raio_min_mm"], r["raio_min_mm"] <= 1.01 * geometrico,
           r["raio_min_mm"])
    fechadas = []
    for esp in ((1.0, 1.0, 1.0), (1.0, 1.0, 2.0), (1.0, 1.0, 3.0)):
        s = B.abrir(domo(R=8.0, esp=esp), "CT")
        e = recusa(A.gerar, s, caixa(s, (-150.0, -6.0, -16.0),
                                     (-80.0, 6.0, 14.0)), par)
        fechadas.append(e.detalhe.get("raio_min_mm")
                        if isinstance(e, A.Bloqueio) and e.detalhe.get(
                            "motivo") == "raio_abaixo_do_piso" else None)
    checar(u"uma curva fechada de verdade (crista de 8 mm, canal com ~13 mm, "
           u"6F com piso de 15) continua bloqueada nos três cortes (%s mm)"
           % u", ".join(u"%.1f" % m if m is not None else u"GEROU"
                        for m in fechadas),
           all(m is not None and m < 15.0 for m in fechadas), fechadas)
    t = np.linspace(-0.5, 0.5, 400)
    arco = np.stack([np.zeros_like(t), 70.0 * np.sin(t),
                     70.0 * np.cos(t)], 1)
    dente = arco.copy()
    dente[:, 2] -= 0.15 * np.exp(-0.5 * (70.0 * t / 5.0) ** 2)
    liso = A.raios_de_curvatura(arco)[0]
    com = A.raios_de_curvatura(dente)[0]
    checar(u"(isca) um afundamento de 0,15 mm num arco de 70 mm, o tamanho "
           u"do erro de fase, já baixa o raio medido para %.0f mm"
           % np.nanmin(com[np.isfinite(com)]),
           abs(np.nanmin(liso[np.isfinite(liso)]) - 70.0) < 0.7
           and np.nanmin(com[np.isfinite(com)]) < 0.9 * 70.0)


def cilindro_com_entalhe(R=80.0, esp=(1.0, 1.0, 2.0),
                         meia=(110.0, 110.0, 70.0), entalhe_x=12.0,
                         entalhe_z=18.0, L=40.0):
    nx, ny, nz = [int(round(2 * meia[i] / esp[i])) + 1 for i in range(3)]
    x = (np.arange(nx) - (nx - 1) / 2.0) * esp[0]
    y = (np.arange(ny) - (ny - 1) / 2.0) * esp[1]
    z = (np.arange(nz) - (nz - 1) / 2.0) * esp[2]
    Z, Y, X = np.meshgrid(z, y, x, indexing="ij")
    comprimento = np.where(np.abs(X) <= entalhe_x, entalhe_z, L)
    sd = np.maximum(np.sqrt(X ** 2 + Y ** 2) - R, np.abs(Z) - comprimento)
    frac = np.clip(0.5 - sd / min(esp), 0.0, 1.0)
    img = sitk.GetImageFromArray((-1000.0 + 1020.0 * frac).astype(np.int16))
    img.SetSpacing(tuple(float(e) for e in esp))
    img.SetOrigin((float(x[0]), float(y[0]), float(z[0])))
    return img


def teste_buraco_no_meio():
    secao(u"canal que cai no meio, com canais aceitos dos dois lados: não "
          u"gera")
    s = B.abrir(cilindro_com_entalhe(), "CT")
    e = recusa(A.gerar, s, caixa(s, (-30, -105, -30), (30, -60, 30)),
               {"eixo": "cc", "direcao": "ant"})
    det = getattr(e, "detalhe", {}) or {}
    texto = str(e) if e is not None else u""
    print(u"         · %s" % (det.get("resumo") or texto)[:300])
    checar(u"o entalhe sob os canais do meio: Bloqueio próprio, e não um "
           u"aplicador com buraco central e só um aviso",
           isinstance(e, A.Bloqueio) and det.get("motivo") == "canal_no_meio",
           texto[:200])
    checar(u"diz quais canais caíram (3 e 4 de 6) e que há aceitos dos dois "
           u"lados (1, 2, 5 e 6)",
           det.get("canais_no_meio") == [3, 4]
           and det.get("canais_aceitos") == [1, 2, 5, 6]
           and u"os canais 3 e 4 (dos 6 tentados" in texto
           and u"aceitos dos dois lados (os canais 1, 2, 5 e 6)" in texto,
           (det.get("canais_no_meio"), det.get("canais_aceitos")))
    checar(u"diz por quê: falta pele sob o canal citado, com os mm e os "
           u"lados, e o risco de subcobertura do alvo",
           det.get("canal_citado") in (3, 4) and u"falta pele sob o canal"
           in texto and u"do lado inferior" in texto and u"do lado superior"
           in texto and u"subcobertura do alvo" in texto, texto[:400])
    checar(u"propõe encurtar a caixa na direção dos canais",
           (det.get("propostas") or [u""])[0].startswith(
               u"Encurte a caixa na direção dos canais"),
           det.get("propostas"))
    r = A.gerar(s, caixa(s, (-8, -105, -30), (32, -60, 30)),
                {"eixo": "cc", "direcao": "ant"})
    fora = [a for a in r["avisos"] if u"não coube" in a]
    checar(u"(isca) o mesmo entalhe na borda da caixa: gera %d canais, e os "
           u"%d que caíram na borda ficam como aviso" % (len(r["canais"]),
                                                         len(fora)),
           len(r["canais"]) >= 1 and len(fora) >= 1, (len(r["canais"]),
                                                      fora[:1]))
    um = {"k": 2, "causa": "inclinacao", "invalido_mm": 0.0,
          "motivo": u"o canal desceria quase na vertical (75°; o limite é "
                    u"70°)"}
    b = A.recusa_canal_no_meio([{"k": 0}, {"k": 1}, {"k": 3}], [um], 4, "ant",
                               2, 0, 5.4, 60.0)
    checar(u"qualquer causa no meio bloqueia, e um canal só no singular",
           isinstance(b, A.Bloqueio) and b.detalhe.get("canais_no_meio") == [3]
           and u"o canal 3 (dos 4 tentados" in str(b) and u"não coube"
           in str(b) and u"desceria quase na vertical" in str(b), str(b)[:200])
    checar(u"(isca) canal caído só na borda, ou um canal aceito só: não "
           u"bloqueia",
           A.recusa_canal_no_meio([{"k": 2}, {"k": 3}], [dict(um, k=0)], 4,
                                  "ant", 2, 0, 5.4, 60.0) is None
           and A.recusa_canal_no_meio([{"k": 1}], [dict(um, k=0),
                                                   dict(um, k=2)], 3, "ant",
                                      2, 0, 5.4, 60.0) is None)


def teste_os_dois_eixos(s):
    secao(u"direção dos canais automática: os dois eixos, e fica o que dá "
          u"mais canais")
    cx = caixa(s, (-20, -105, -35), (20, -60, 35))
    r = A.gerar(s, cx, {"eixo": "auto", "direcao": "ant"})
    rc = A.gerar(s, cx, {"eixo": "cc", "direcao": "ant"})
    checar(u"caixa estreita em x e longa em z: a automática traça os dois e "
           u"fica com a laterolateral (%d canais contra %d)"
           % (len(r["canais"]), len(rc["canais"])),
           r["eixo_canal"] == 0 and len(r["canais"]) > len(rc["canais"])
           and [t["eixo"] for t in r["eixos_tracados"]] == [2, 0]
           and all(t["tracado"] for t in r["eixos_tracados"]),
           r["eixos_tracados"])
    checar(u"  (isca) a regra fixa de antes (craniocaudal) dava menos canais "
           u"na mesma caixa", rc["eixo_canal"] == 2 and len(rc["canais"]) == 4,
           len(rc["canais"]))
    av = [a for a in r["avisos"] if a.startswith(u"Direção dos canais")]
    checar(u"  e diz qual escolheu, e quanto coube no outro",
           av == [u"Direção dos canais escolhida pelo app: laterolateral "
                  u"(direita–esquerda), com %d canais; na craniocaudal, "
                  u"couberam 4." % len(r["canais"])], av)
    par = dict(A.linhas_de_parametros(r))
    checar(u"  a ficha diz que a direção foi escolhida pelo app",
           par.get(u"Direção dos canais") == u"laterolateral "
           u"(direita–esquerda) (escolhida pelo app)", par.get(u"Direção dos canais"))
    checar(u"a direção escolhida no formulário é respeitada, sem aviso de "
           u"escolha", not [a for a in rc["avisos"]
                            if a.startswith(u"Direção dos canais")]
           and dict(A.linhas_de_parametros(rc)).get(u"Direção dos canais")
           == u"craniocaudal")
    q = caixa(s, (-30, -105, -30), (30, -60, 30))
    ra = A.gerar(s, q, {"eixo": "auto", "direcao": "ant"})
    rq = A.gerar(s, q, {"eixo": "cc", "direcao": "ant"})
    checar(u"caixa quadrada: o padrão já dá todos os canais que o outro "
           u"caberia, e o outro nem é traçado (o mesmo STL do padrão)",
           ra["stl"] == rq["stl"] and ra["eixos_tracados"][1]["tracado"] is False
           and u"caberiam no máximo 6" in u" ".join(ra["avisos"]),
           ra["eixos_tracados"])


def teste_automatico_procura_eixo_seguro():
    secao(u"automático: menos canais seguros vencem mais canais abaixo do piso")
    s = B.abrir(cilindro(R=20.0, L=50.0, esp=(0.5, 0.5, 1.0),
                         meia=(40.0, 40.0, 60.0)), "CT")
    cx = caixa(s, (-14, -42, -32), (14, -14, 32))
    p = {"direcao": "ant", "cateter": "proguide",
         "afterloader": "microselectron_digital"}
    e = recusa(A.gerar, s, cx, dict(p, eixo="ll"))
    checar(u"a direção curva, mesmo com mais canais, continua bloqueada pelo piso",
           isinstance(e, A.Bloqueio) and e.detalhe.get("motivo")
           == "raio_abaixo_do_piso", e)
    seguro = A.gerar(s, cx, dict(p, eixo="cc"))
    automatico = A.gerar(s, cx, dict(p, eixo="auto"))
    checar(u"o automático tenta o segundo eixo e preserva o STL do eixo seguro",
           automatico["eixo_canal"] == seguro["eixo_canal"] == 2
           and automatico["stl"] == seguro["stl"]
           and all(t["tracado"] for t in automatico["eixos_tracados"]),
           automatico["eixos_tracados"])
    checar(u"o aviso explica por que o eixo com mais canais não foi usado",
           u"não passaram nas conferências de segurança"
           in u" ".join(automatico["avisos"]))


def teste_fundo_cego_sem_pele_alem_do_fundo(s):
    secao(u"fundo cego: não exige pele além do fundo, onde não há cateter")
    P = {"trajeto": "cego", "entrada": "inicio", "raio_mm": 1.5}
    checar(u"no aberto, o trecho exigido é a caixa inteira",
           A.trecho_exigido(10, 410, 0.0, 100.0, 0.25,
                            dict(P, trajeto="aberto")) == (10, 410))
    checar(u"no cego com entrada no início, ele para no fundo (raio + 2 mm "
           u"antes da face oposta)",
           A.trecho_exigido(10, 411, 0.0, 100.0, 0.25, P) == (10, 397))
    checar(u"no cego com entrada no fim, ele começa no fundo",
           A.trecho_exigido(10, 411, 0.0, 100.0, 0.25,
                            dict(P, entrada="fim")) == (24, 411))
    cx = caixa(s, (-15, -105, -30), (15, -60, 86))
    e = recusa(A.gerar, s, cx, {"eixo": "cc", "direcao": "ant"})
    checar(u"a caixa passa do fim do cilindro: no aberto, nenhum canal cabe "
           u"(o canal sai pela face sem pele embaixo)",
           isinstance(e, A.Bloqueio) and e.detalhe.get("motivo")
           == "nenhum_canal", str(e)[:160])
    par = {"eixo": "cc", "direcao": "ant", "trajeto": "cego",
           "entrada": "inicio"}
    r = A.gerar(s, cx, par)
    checar(u"no cego, os canais cabem: o trecho sem pele fica além do fundo "
           u"(%d canais, malha fechada, fundo fechado)" % len(r["canais"]),
           len(r["canais"]) == 3 and r["malha"]["fechada"] and r["pecas"] == 1,
           (len(r["canais"]), r["malha"]["fechada"]))
    lin = linhas_lps(s, r)
    fundo = lin[0][-1]
    alem = fundo + np.array([0, 0, A.FUNDO_CEGO_PAREDE_MM / 2.0
                             + r["parametros"]["raio_mm"]])
    checar(u"  e além do fundo há parede (a conferência da malha continua)",
           bool(B.dentro_da_malha(tri_lps(r["stl"]), np.array([alem]))[0]))
    original = A.trecho_exigido
    A.trecho_exigido = lambda i0, i1, *a: (i0, i1)
    try:
        e2 = recusa(A.gerar, s, cx, par)
    finally:
        A.trecho_exigido = original
    checar(u"  (isca) exigindo pele na caixa inteira, como antes, o mesmo "
           u"cego seria recusado", isinstance(e2, A.Bloqueio)
           and e2.detalhe.get("motivo") == "nenhum_canal", str(e2)[:160])


def _funcao_js(js, nome):
    i = js.find(u"function %s(" % nome)
    if i < 0:
        return u""
    k, prof = js.find(u"{", i), 0
    for j in range(k, len(js)):
        if js[j] == u"{":
            prof += 1
        elif js[j] == u"}":
            prof -= 1
            if prof == 0:
                return js[i:j + 1]
    return u""


_HARNESS_SUGERIDA = u"""
var NOS = {};
function no(id){ var n = {id: id, filhos: [], classList: {add: function(){},
  remove: function(){}}, textContent: '', parentNode: null,
  appendChild: function(c){ c.parentNode = this; this.filhos.push(c) },
  removeChild: function(c){ this.filhos.splice(this.filhos.indexOf(c), 1); c.parentNode = null }};
  return n }
function el(id){ return NOS[id] || (NOS[id] = no(id)) }
var document = {createElement: function(){ return no('') }};
var window = {RETRAD: 0, radaiRetraduzir: function(){ window.RETRAD++ }};
function escreve(a, t){ a.textContent = t }
function aviso(a, t, c){ var p = no(''); p.textContent = t; a.appendChild(p) }
function tremerCampo(){}
function validarCampo(){}
var CAMPO_AP = {};
var DESENHOS = 0;
function desenharCaixas(){ DESENHOS++ }
function desenharE(){ DESENHOS++ }
var BO = {caixa: {x0: 1, x1: 2, y0: 3, y1: 4, z0: 5, z1: 6}};
var D = %s;
mostrarBloqueio(D);
var antes = JSON.stringify(BO.caixa);
var bt = el('bo-avisos').filhos.filter(function(f){ return f.id === 'bo-ap-sugerida' })[0];
var tinha = !!bt, rot = bt ? bt.textContent : '';
var LINHAS = el('bo-avisos').filhos.map(function(f){ return f.textContent });
var RETRAD = window.RETRAD;
if(bt) bt.onclick();
console.log('JSON:' + JSON.stringify({antes: antes, depois: BO.caixa, tinha: tinha,
  rotulo: rot, linhas: LINHAS, retrad: RETRAD, retrad_clique: window.RETRAD - RETRAD,
  estado: el('bo-estado').textContent, desenhos: DESENHOS,
  sobrou: el('bo-avisos').filhos.filter(function(f){ return f.id === 'bo-ap-sugerida' }).length}));
"""


def _sugerida_no_node(js, d):
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        return None
    fn = u"\n".join(_funcao_js(js, n) for n in ("mostrarBloqueio",
                                                "botaoDaSugerida"))
    arq = os.path.join(_cleanup.temporaria("radai_teste_sugerida_js_"), "t.js")
    io.open(arq, "w", encoding="utf-8").write(
        fn + _HARNESS_SUGERIDA % json.dumps(d, ensure_ascii=False))
    p = subprocess.run([node, arq], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    for ln in reversed((p.stdout or u"").splitlines()):
        if ln.startswith(u"JSON:"):
            return json.loads(ln[5:])
    return {"erro": (p.stderr or u"")[-300:]}


def teste_caixa_sugerida(s):
    secao(u"nenhum canal na caixa inteira: a caixa aparada onde eles cabem, "
          u"proposta e nunca aplicada")
    V = np.ones((5, 40), dtype=bool)
    V[:, :6] = False
    V[2, 30:] = False
    iv = A.intervalo_com_canais(V, 1.0, 10.0)
    checar(u"o intervalo fica com os cinco canais onde todos têm pele, e não "
           u"com o trecho em que o do meio cai (%s)" % (iv,),
           iv is not None and iv[1:] == (6, 30, 5), iv)
    W = np.ones((5, 40), dtype=bool)
    W[2, :] = False
    checar(u"  canal do meio sem pele em lugar nenhum: sem sugestão (seria "
           u"o buraco que a geração recusa)",
           A.intervalo_com_canais(W, 1.0, 10.0) is None)
    curto = np.ones((3, 40), dtype=bool)
    curto[:, 8:] = False
    checar(u"  e o trecho menor que o mínimo não vira sugestão",
           A.intervalo_com_canais(curto, 1.0, 10.0) is None
           and A.intervalo_com_canais(curto, 1.0, 7.0) is not None)
    lo, hi = (-15, -105, -30), (15, -60, 95)
    cx = caixa(s, lo, hi)
    par = {"eixo": "cc", "direcao": "ant"}
    e = recusa(A.gerar, s, cx, par)
    det = getattr(e, "detalhe", {}) or {}
    sug = det.get("caixa_sugerida") or {}
    print(u"         · %s" % ((det.get("propostas") or [u""])[-1])[:300])
    cxn = B.normalizar_caixa(s, cx)
    checar(u"a recusa continua recusa, e leva a caixa sugerida",
           isinstance(e, A.Bloqueio) and det.get("motivo") == "nenhum_canal"
           and sug, str(e)[:200])
    checar(u"  aparada só na direção dos canais (z), dentro da desenhada",
           sug and all(abs(sug[k] - cxn[k]) < 1e-6 for k in
                       ("x0", "x1", "y0", "y1"))
           and abs(sug["z0"] - cxn["z0"]) < 1e-6 and sug["z1"] < cxn["z1"] - 5,
           (sug, cxn))
    checar(u"  e a última proposta, logo antes do botão, diz quanto deixa de "
           u"cobrir e que a caixa só muda com o clique",
           (det.get("propostas") or [u""])[-1].startswith(u"Caixa sugerida:")
           and u"deixa de cobrir" in det["propostas"][-1]
           and u"«Usar a caixa sugerida»" in det["propostas"][-1]
           and det["propostas"][0].startswith(u"Encurte a caixa"),
           det.get("propostas"))
    r = A.gerar(s, sug, par) if sug else None
    checar(u"na caixa sugerida, o aplicador sai com os canais que ela "
           u"prometeu (%s)" % (len(r["canais"]) if r else None),
           r is not None and len(r["canais"]) == det.get("sugerida_canais")
           and r["malha"]["fechada"], det.get("sugerida_canais"))
    original = A.caixa_sugerida
    A.caixa_sugerida = lambda *a, **k: None
    try:
        e0 = recusa(A.gerar, s, cx, par)
    finally:
        A.caixa_sugerida = original
    checar(u"  (isca) sem a sugestão, a recusa não traz caixa nenhuma",
           isinstance(e0, A.Bloqueio)
           and "caixa_sugerida" not in (e0.detalhe or {}), str(e0)[:120])
    import radai_bolus_screen as T
    d = {"erro": str(e), "bloqueio": A._json(det)}
    o = _sugerida_no_node(T.JS, d)
    if o is None:
        print(u"         · node ausente: o botão NÃO foi medido")
        return
    checar(u"a tela mostra «Usar a caixa sugerida», e a caixa NÃO muda "
           u"sozinha ao mostrar a recusa",
           o.get("tinha") and o.get("rotulo") == u"Usar a caixa sugerida"
           and json.loads(o.get("antes") or "{}") == {"x0": 1, "x1": 2, "y0": 3,
                                                     "y1": 4, "z0": 5, "z1": 6},
           str(o)[:300])
    checar(u"  só o clique troca a caixa pela sugerida, redesenha e diz para "
           u"conferir o alvo e gerar de novo",
           o.get("depois") == {k: float(sug[k]) for k in sug}
           and o.get("desenhos") == 2 and o.get("sobrou") == 0
           and u"confira se o alvo continua dentro" in (o.get("estado") or u""),
           str(o)[:300])
    checar(u"  e a recusa e o clique pedem a tradução do que escreveram (o "
           u"botão e o aviso saem nos doze idiomas)",
           o.get("retrad") == 1 and o.get("retrad_clique") == 1,
           (o.get("retrad"), o.get("retrad_clique")))
    o2 = _sugerida_no_node(T.JS, {"erro": str(e0), "bloqueio": A._json(e0.detalhe)})
    checar(u"  (isca) recusa sem sugestão: nenhum botão",
           o2 is not None and o2.get("tinha") is False, str(o2)[:200])


def teste_a_sugerida_que_vira_a_colocacao_e_dita(s):
    secao(u"a caixa aparada em que a colocação automática viraria: sai, e a "
          u"tela diz numa linha")
    cx = caixa(s, (-15, -105, -30), (15, -60, 95))
    par = {"eixo": "cc", "direcao": "auto"}
    e_auto = recusa(A.gerar, s, cx, par)
    det_a = getattr(e_auto, "detalhe", {}) or {}
    checar(u"na colocação automática que não vira, a sugestão continua "
           u"(sem a linha do descarte)",
           det_a.get("colocacao_automatica") and det_a.get("caixa_sugerida")
           and A.SUGERIDA_DESCARTADA not in (det_a.get("propostas") or [])
           and "sugerida_descartada" not in det_a, str(e_auto)[:200])
    real = B.direcao_automatica
    vistas = []

    def vira(solido, lo, hi):
        d = real(solido, lo, hi)
        vistas.append(d)
        return d if len(vistas) == 1 else (u"esq" if d != u"esq" else u"dir")
    B.direcao_automatica = vira
    try:
        e = recusa(A.gerar, s, cx, par)
    finally:
        B.direcao_automatica = real
    det = getattr(e, "detalhe", {}) or {}
    desc = det.get("sugerida_descartada") or {}
    prop = det.get("propostas") or []
    print(u"         · %s" % (prop[-1:] or [u""])[0][:200])
    checar(u"a recusa continua recusa, sem caixa sugerida e sem botão",
           isinstance(e, A.Bloqueio) and det.get("motivo") == "nenhum_canal"
           and "caixa_sugerida" not in det, str(e)[:200])
    checar(u"  e o descarte fica no detalhe, com a colocação de agora e a que "
           u"a caixa aparada teria (%s)" % (desc,),
           desc.get("colocacao") == vistas[0]
           and desc.get("colocacao_na_sugerida") not in (None, vistas[0])
           and len(vistas) == 2, (desc, vistas))
    checar(u"  e a última proposta é a linha que diz o descarte",
           prop[-1:] == [A.SUGERIDA_DESCARTADA]
           and A.SUGERIDA_DESCARTADA in str(e), prop[-1:])
    original = A.caixa_sugerida
    A.caixa_sugerida = lambda *a, **k: None
    B.direcao_automatica = vira
    try:
        vistas[:] = []
        e0 = recusa(A.gerar, s, cx, par)
    finally:
        A.caixa_sugerida = original
        B.direcao_automatica = real
    checar(u"  (isca) com a sugestão sumindo calada, como antes, a linha não "
           u"está e a checagem acusa",
           isinstance(e0, A.Bloqueio)
           and A.SUGERIDA_DESCARTADA not in ((e0.detalhe or {}).get(
               "propostas") or []), str(e0)[:160])
    import radai_bolus_screen as T
    o = _sugerida_no_node(T.JS, {"erro": str(e), "bloqueio": A._json(det)})
    if o is None:
        print(u"         · node ausente: a linha na tela NÃO foi medida")
        return
    checar(u"a tela mostra a linha do descarte, e nenhum botão",
           o.get("tinha") is False
           and A.SUGERIDA_DESCARTADA in (o.get("linhas") or []), str(o)[:300])
    checar(u"  e pede a tradução do que acabou de escrever (a linha sai nos "
           u"doze idiomas)", o.get("retrad") == 1, o.get("retrad"))
    sem_trad = T.JS.replace(
        u"botaoDaSugerida(av, d.bloqueio.caixa_sugerida);\n"
        u"  if(window.radaiRetraduzir) window.radaiRetraduzir();",
        u"botaoDaSugerida(av, d.bloqueio.caixa_sugerida);", 1)
    oi = _sugerida_no_node(sem_trad, {"erro": str(e), "bloqueio": A._json(det)})
    checar(u"  (isca) sem o pedido de tradução, a linha ficaria em português "
           u"em toda língua, e a checagem acusa",
           sem_trad != T.JS and oi is not None and oi.get("retrad") == 0,
           str(oi)[:160])
    o0 = _sugerida_no_node(T.JS, {"erro": str(e0),
                                  "bloqueio": A._json(e0.detalhe)})
    checar(u"  (isca) sem o conserto, a tela não tinha linha nem botão",
           o0 is not None and o0.get("tinha") is False
           and A.SUGERIDA_DESCARTADA not in (o0.get("linhas") or []),
           str(o0)[:200])


MOTIVO_ANTIGO = (u"fora do corpo, sob outro objeto, ou a caixa não sai da "
                 u"pele o bastante")


def _mensagem_antiga(descartados):
    if not descartados:
        return u""
    motivo = (u"a pele não está sob o canal em %d mm do trajeto (%s)"
              % (max(1, int(math.ceil(descartados[0]["invalido_mm"]))),
                 MOTIVO_ANTIGO))
    return (u"Nenhum canal coube na caixa: %s. Mude a caixa para a pele ficar "
            u"sob todo o trajeto, ou troque a direção dos canais." % motivo)


def _numeros(texto):
    return [float(x.replace(u",", u".")) for x in
            re.findall(r"(\d+(?:,\d+)?) mm", texto)]


def teste_recusa_diz_por_que(s):
    secao(u"nenhum canal coube: a colocação, o melhor canal e as causas")
    c = A.causas_do_trajeto([True, False, False, True, True, True, True,
                             True], [3, 0, 0, 0, 2, 2, 5, 1],
                            [False, False, False, False, False, True, True,
                             False], 0.5)
    checar(u"as três causas contadas em separado, por passo (sem pele 2, "
           u"topo 1, objeto 2) e por face (%s)" % c,
           c["sem_pele_passos"] == 2 and c["topo_passos"] == 1
           and c["objeto_passos"] == 2 and c["validos_passos"] == 3
           and c["inicio_passos"] == 3 and c["fim_passos"] == 2
           and c["sem_pele_inicio_passos"] == 2
           and c["sem_pele_fim_passos"] == 0, c)

    cx = caixa(s, (-95, -105, -95), (95, -60, -50))
    e = recusa(A.gerar, s, cx, {"eixo": "ll", "direcao": "ant"})
    texto = str(e) if e is not None else u""
    det = getattr(e, "detalhe", {}) or {}
    print(u"         · %s" % (det.get("resumo") or texto)[:300])
    checar(u"a caixa que passa da pele: recusa, com o motivo próprio",
           isinstance(e, A.Bloqueio) and det.get("motivo") == "nenhum_canal",
           texto[:200])
    checar(u"diz a colocação e a direção dos canais",
           u"Colocação anterior (escolhida no formulário)" in texto
           and u"laterolateral" in texto, texto[:200])
    checar(u"cita o melhor canal, e não o primeiro: o primeiro não tem pele "
           u"nenhuma (passa do fim do corpo), os outros têm pele no meio",
           det.get("melhor_canal") in (2, 3) and det.get("canais_tentados")
           == 4 and u"o canal %d" % det.get("melhor_canal", 0) in texto,
           (det.get("melhor_canal"), det.get("canais_tentados")))
    mm = det.get("causas_mm") or {}
    checar(u"no melhor canal, ~68 mm sem pele, metade de cada lado, e nada "
           u"de topo ou objeto (%s)" % mm,
           60 <= mm.get("sem_pele", 0) <= 76 and mm.get("topo") == 0
           and mm.get("objeto") == 0
           and abs(mm.get("lado_inicio", 0) - mm.get("lado_fim", 0)) <= 4, mm)
    checar(u"diz quanto do trajeto tem pele, e que falta dos dois lados",
           u"tem pele sob" in texto and u"do lado direita" in texto
           and u"do lado esquerda" in texto, texto[:300])
    checar(u"as causas saem separadas, não as três numa frase só",
           MOTIVO_ANTIGO not in texto and u"topo da caixa" not in
           det.get("resumo", u""), texto[:300])
    checar(u"propõe encurtar a caixa na direção dos canais, primeiro",
           (det.get("propostas") or [u""])[0].startswith(
               u"Encurte a caixa na direção dos canais"),
           det.get("propostas"))
    antiga = _mensagem_antiga(det.get("descartados") or [])
    checar(u"(isca) a mensagem antiga citava o canal 1, com %s mm, e "
           u"misturava as causas" % (_numeros(antiga)[:1] or [u"?"])[0],
           MOTIVO_ANTIGO in antiga and _numeros(antiga)
           and _numeros(antiga)[0] > 150, antiga[:160])

    cx2 = caixa(s, (-30, -83, -20), (30, -50, 20))
    e2 = recusa(A.gerar, s, cx2, {"eixo": "ll", "direcao": "ant"})
    det2 = getattr(e2, "detalhe", {}) or {}
    mm2 = det2.get("causas_mm") or {}
    print(u"         · %s" % (det2.get("resumo") or str(e2))[:300])
    checar(u"a caixa colada na pele: a causa é o topo da caixa (%s)" % mm2,
           det2.get("motivo") == "nenhum_canal" and mm2.get("topo", 0) >= 30
           and mm2.get("sem_pele") == 0 and u"topo da caixa"
           in det2.get("resumo", u""), str(e2)[:200])
    checar(u"e propõe afastar da pele a face anterior da caixa",
           (det2.get("propostas") or [u""])[0].startswith(
               u"Afaste da pele a face anterior da caixa"),
           det2.get("propostas"))
    e3 = recusa(A.gerar, s, cx, {"eixo": "ll", "direcao": "auto"})
    checar(u"na colocação automática, a recusa diz que foi o app que "
           u"escolheu", e3 is not None and u"(escolhida pelo app)" in str(e3),
           str(e3)[:200])


def teste_ficha_e_pacote(r_verde, r_amarelo):
    secao(u"a ficha e o pacote: o STL, a ficha, e os avisos que não somem")
    nome_zip, dados, nome_stl = A.pacote(r_verde, u"a1b2c3d4e5f6a7b8",
                                         quando=u"2026-10-14 10:00")
    z = zipfile.ZipFile(io.BytesIO(dados))
    nomes = sorted(z.namelist())
    checar(u"o .zip leva o STL e a ficha, e só (%s)" % nomes,
           len(nomes) == 2 and nome_stl in nomes
           and any(n.endswith(u"_FICHA.txt") for n in nomes))
    checar(u"o STL do .zip é o gerado, byte a byte",
           z.read(nome_stl) == r_verde["stl"])
    bruto = z.read([n for n in nomes if n.endswith(u"_FICHA.txt")][0])
    checar(u"a ficha em UTF-8 com BOM e CRLF (o Bloco de Notas do LTSB)",
           bruto.startswith(b"\xef\xbb\xbf")
           and b"\n" not in bruto.replace(b"\r\n", b""))
    texto = bruto.decode("utf-8-sig")
    for e in A.EXIGENCIAS:
        checar(u"a ficha diz: %s" % e[:50], e in texto)
    checar(u"verde: sem as exigências da curva",
           not any(e in texto for e in A.EXIGENCIAS_DA_CURVA))
    for rot, _v in A.linhas_de_parametros(r_verde):
        checar(u"a ficha traz o parâmetro «%s»" % rot, rot in texto)
    checar(u"as seis referências e a pesquisa de curvatura",
           all(x in texto for x in A.REFERENCIAS)
           and all(x in texto for x in A.PESQUISA_DE_CURVATURA))
    checar(u"o material com as referências dele",
           A.MATERIAL in texto and A.MATERIAL_REFERENCIAS in texto)
    checar(u"verde: a face de entrada, e nenhum bloco de trechos amarelos",
           u"contam da face inferior" in texto
           and u"Trechos de curva amarela" not in texto)
    checar(u"rascunho não aprovado, e nada da série",
           u"RASCUNHO NÃO APROVADO" in texto and u"ZZSENTINELA" not in texto)
    am = A.ficha(r_amarelo, u"x.stl")
    checar(u"amarela: as quatro exigências da curva na ficha",
           all(e in am for e in A.EXIGENCIAS_DA_CURVA) and u"AMARELA" in am)
    estranho = A.nome_do_aplicador(r_verde, u"../BELTRANO^ISCA 1.2.840/xy")
    checar(u"(isca) sorteio com texto estranho não passa para o nome (%s)"
           % estranho, u"BELTRANO" not in estranho and u"/" not in estranho
           and u"." not in estranho)
    checar(u"o nome diz o que é (%s)" % nome_zip,
           nome_zip.startswith(u"RadAI_applicator_DRAFT_6ch_d5mm_open_")
           and nome_zip.endswith(u"a1b2c3d4.zip"))
    j = A.resumo(r_verde)
    json.dumps(j)
    checar(u"o resumo é JSON, sem malha, máscara nem bytes",
           "stl" not in j and "mask" not in j
           and "linhas_centrais_quadro" not in j
           and j["parametros_tela"] and j["canais_tela"])


def teste_ato(r_verde, r_amarelo):
    secao(u"o ato declarado do aplicador, e o da curva amarela")
    checar(u"com o ato e a frase, passa",
           A.conferir_ato(r_verde, True, A.FRASE_DO_ATO))
    for nome, args in ((u"sem declarar", (False, A.FRASE_DO_ATO)),
                       (u"1 em vez de true", (1, A.FRASE_DO_ATO)),
                       (u"frase do bólus", (True, B.FRASE_DO_ATO)),
                       (u"sem frase", (True, None))):
        checar(u"recusa: %s" % nome,
               recusa(A.conferir_ato, r_verde, *args) is not None)
    checar(u"amarela sem a declaração da curva: recusa",
           recusa(A.conferir_ato, r_amarelo, True, A.FRASE_DO_ATO) is not None)
    checar(u"amarela com as duas: passa",
           A.conferir_ato(r_amarelo, True, A.FRASE_DO_ATO, True,
                          A.FRASE_DA_CURVA))
    checar(u"a frase diz rascunho, segunda TC, passagem e dosimetria",
           all(x in A.FRASE_DO_ATO for x in (
               u"rascunho sujeito a revisão física e médica",
               u"segunda TC", u"cabo de checagem", u"dosimetria")))
    linha = A.linha_do_ato(r_verde, u"RadAI_applicator_x.stl")
    checar(u"a linha do registro diz o ato e os números, sem a série",
           u"exportado por ato declarado" in linha and u"6 canais" in linha
           and u"ZZSENTINELA" not in linha, linha)


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


def teste_rotas(s_grande, s_pequeno, cx_pequeno):
    secao(u"as rotas: gerar, bloquear, e exportar só com o ato")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import radai_bolus_screen as T
    app = FastAPI()
    ouvidos = []
    T.montar(app, ouvidos.append)
    cli = TestClient(app)
    T._esquecer()
    T._S.update({"b": "bgrande", "serie": s_grande, "visto": time.time()})
    cx = caixa(s_grande, (-30, -105, -30), (30, -60, 30))
    g = cli.post("/api/bolus/aplicador/gerar", json={
        "b": "bgrande", "caixa": cx, "eixo": "cc", "direcao": "ant"}).json()
    checar(u"gerar devolve o resumo com o id", g.get("r") and
           g.get("peca") == "aplicador" and len(g.get("canais") or []) == 6, g)
    checar(u"o resumo não carrega a série",
           u"ZZSENTINELA" not in json.dumps(g) and "stl" not in g)
    rid = g["r"]
    v = cli.get("/api/bolus/volume", params={"b": "bgrande", "qual": "bolus",
                                              "r": rid})
    checar(u"a prévia do aplicador tem o tamanho declarado",
           v.status_code == 200
           and len(v.content) == int(np.prod(g["previa"]["forma"])))
    c = cli.get("/api/bolus/corte", params={"b": "bgrande", "plano": "ax",
                                            "i": 50, "r": rid})
    checar(u"o corte com o aplicador responde em PNG",
           c.status_code == 200 and c.content[:4] == b"\x89PNG")
    ATO = {"b": "bgrande", "r": rid, "declaro": True, "frase": A.FRASE_DO_ATO}
    checar(u"o STL do bólus NÃO exporta um aplicador (409)",
           cli.post("/api/bolus/stl", json=dict(
               ATO, frase=B.FRASE_DO_ATO)).status_code == 409)
    sem = cli.post("/api/bolus/aplicador/exportar", json={"b": "bgrande",
                                                          "r": rid})
    checar(u"SEM o ato: 409", sem.status_code == 409)
    checar(u"com a frase do bólus: 409",
           cli.post("/api/bolus/aplicador/exportar", json=dict(
               ATO, frase=B.FRASE_DO_ATO)).status_code == 409)

    def ler_atos():
        try:
            return io.open(T.arquivo_de_atos(), encoding="utf-8").read()
        except IOError:
            return u""

    antes = ler_atos()
    com = cli.post("/api/bolus/aplicador/exportar", json=ATO)
    nome = com.headers.get("x-radai-nome", u"")
    checar(u"COM o ato: sai o .zip (%s)" % nome,
           com.status_code == 200 and nome.endswith(u".zip")
           and com.content[:2] == b"PK", com.status_code)
    if com.status_code == 200:
        z = zipfile.ZipFile(io.BytesIO(com.content))
        stl = [n for n in z.namelist() if n.endswith(u".stl")]
        checar(u"com o STL do aplicador dentro",
               stl and B.cabecalho_seguro(z.read(stl[0])[:80]))
    novo = ler_atos()[len(antes):]
    checar(u"o ato fica no arquivo dos atos, sem a série",
           u"STL do APLICADOR exportado por ato declarado" in novo
           and u"ZZSENTINELA" not in novo, novo[-160:])
    checar(u"e chega ao log do vigia",
           ouvidos and u"APLICADOR" in ouvidos[-1], ouvidos[-1:])
    gravar = T._gravar_ato

    def quebra(linha):
        raise IOError("disco cheio (dublado)")

    try:
        T._gravar_ato = quebra
        falhou = cli.post("/api/bolus/aplicador/exportar", json=ATO)
    finally:
        T._gravar_ato = gravar
    checar(u"sem registrar o ato, o .zip NÃO sai (500)",
           falhou.status_code == 500 and falhou.content[:2] != b"PK")
    fonte = io.open(_componentes.fonte("app/radai_bolus_screen.py"),
                    encoding="utf-8").read()
    for chamada in ("conferir_ato", "_gravar_ato"):
        checar(u"a rota confere %s ANTES de montar a resposta" % chamada,
               _rota_chama_antes(fonte, "/api/bolus/aplicador/exportar",
                                 chamada))
    k = fonte.index(u'@app.post("/api/bolus/aplicador/exportar")')
    isca = fonte[:k] + fonte[k:].replace(u"_gravar_ato(linha)",
                                         u"(lambda *a: None)(linha)", 1)
    checar(u"(isca) sem a gravação do ato na rota do aplicador, a checagem "
           u"reprova", isca != fonte and not _rota_chama_antes(
               isca, "/api/bolus/aplicador/exportar", "_gravar_ato"))

    T._esquecer()
    T._S.update({"b": "bpeq", "serie": s_pequeno, "visto": time.time()})
    b = cli.post("/api/bolus/aplicador/gerar", json={
        "b": "bpeq", "caixa": cx_pequeno, "eixo": "ll", "direcao": "ant",
        "cateter": "proguide"}).json()
    checar(u"abaixo do piso, a rota devolve o bloqueio, as propostas e o "
           u"campo que treme",
           b.get("erro") and (b.get("bloqueio") or {}).get("motivo")
           == "raio_abaixo_do_piso" and b.get("campo") == "raio"
           and len(b["bloqueio"].get("propostas") or []) == 4, b)
    e = cli.post("/api/bolus/aplicador/gerar", json={
        "b": "bpeq", "caixa": cx_pequeno, "canal_mm": 1.5}).json()
    checar(u"canal mais estreito que o cateter: a rota diz o campo",
           e.get("campo") == "canal_mm" and e.get("bloqueio"), e)
    for pedido in (16, 20, 34):
        e = cli.post("/api/bolus/aplicador/gerar", json={
            "b": "bpeq", "caixa": cx_pequeno, "raio_padrao_mm": pedido}).json()
        checar(u"raio padrão de %d mm: a rota recusa, diz que começa em 35 mm "
               u"e o campo que treme" % pedido,
               e.get("erro") and e.get("campo") == "raio_padrao_mm"
               and u"começa em 35 mm" in e.get("erro", u""), e)
    am = cli.post("/api/bolus/aplicador/gerar", json={
        "b": "bpeq", "caixa": cx_pequeno, "eixo": "ll",
        "direcao": "ant"}).json()
    ATO_A = {"b": "bpeq", "r": am.get("r"), "declaro": True,
             "frase": A.FRASE_DO_ATO}
    checar(u"amarela: sem a declaração da curva, 409",
           am.get("classe") == "amarelo" and cli.post(
               "/api/bolus/aplicador/exportar", json=ATO_A).status_code == 409)
    checar(u"amarela: com as duas declarações, sai",
           cli.post("/api/bolus/aplicador/exportar", json=dict(
               ATO_A, declaro_curva=True, frase_curva=A.FRASE_DA_CURVA))
           .status_code == 200)
    T._esquecer()


def teste_tela():
    secao(u"a tela: a escolha da peça, o formulário com «?», o ato e o brilho")
    import radai_bolus_screen as T
    import radai_ui
    p = T.pagina()
    checar(u"nenhum marcador @X@ sobrou", not re.findall(r"@[A-Z0-9_]+@", p),
           re.findall(r"@[A-Z0-9_]+@", p))
    checar(u"a escolha da peça: bólus (marcado) ou aplicador",
           re.search(r'name="bo-peca" value="bolus" checked', p)
           and u'name="bo-peca" value="aplicador"' in p)
    m = re.search(r'<div class="bo-ctl" id="bo-ctl-ap"[^>]*>', p)
    checar(u"o painel do aplicador nasce escondido", m and u"hidden" in
           m.group(0))
    for i in ("bo-ap-afterloader", "bo-ap-cateter", "bo-ap-od", "bo-ap-raio",
              "bo-ap-canal", "bo-ap-dist", "bo-ap-esp", "bo-ap-corpo",
              "bo-ap-dir", "bo-ap-eixo", "bo-ap-trajeto", "bo-ap-entrada"):
        checar(u"«%s» tem `<label for>`" % i,
               re.search(r'<label[^>]*\bfor="%s"' % i, p))
    painel = p[p.index(u'id="bo-ctl-ap"'):p.index(u'id="bo-ap-pecas"')]
    checar(u"o formulário tem um «?» por item, inclusive o diâmetro externo, "
           u"a direção de colocação e a superfície (%d)"
           % painel.count(u'class="ui-ajuda'),
           painel.count(u'class="ui-ajuda') >= 15)
    for campo in ("bo-ap-od", "bo-ap-dir"):
        k = painel.index(u'id="%s"' % campo)
        resto = painel[k:painel.index(u'<div class="g"', k)]
        checar(u"«%s» tem o «?» dele" % campo, u'class="ui-ajuda' in resto)
    for a in A.AFTERLOADERS + A.CATETERES:
        checar(u"o menu traz «%s» com o número e a fonte curta" % a["nome"],
               (u">%s<" % T._esc(T.opcao_do_menu(a))) in painel
               and (u"%d mm (" % int(a["piso_mm"])) in T.opcao_do_menu(a))
    checar(u"a opção do VariSource iX diz, no próprio menu, que o número "
           u"não foi conferido", u"VariSource iX — 17 mm (número NÃO "
           u"conferido" in painel)
    checar(u"o «?» do raio está na tela, com o Laan 2019",
           u"Laan 2019" in painel and u"50 mm" in painel)
    m = re.search(r'<input type="number" id="bo-ap-raio"[^>]*>', painel)
    checar(u"o raio padrão é campo de digitar (35 mm), e não um rótulo",
           m and u'value="35.0"' in m.group(0), m and m.group(0))
    checar(u"o campo nasce com o mínimo de 35 mm, e não com o piso",
           m and u'min="35.0"' in m.group(0), m and m.group(0))
    checar(u"o mínimo do campo é o maior entre o piso e os 35 mm, e o raio "
           u"vai ao servidor",
           u"var minimo = Math.max(piso, AP.padrao);" in T.JS
           and u"el('bo-ap-raio').min = minimo;" in T.JS
           and u"el('bo-ap-raio').min = piso;" not in T.JS
           and u"raio_padrao_mm: +el('bo-ap-raio').value" in T.JS
           and u"raio_padrao_mm: 'bo-ap-raio'" in T.JS
           and u"'bo-ap-raio', 'bo-ap-canal'" in T.JS)
    m = re.search(r'<div class="g"([^>]*)><label class="g-rot" '
                  r'for="bo-ap-entrada"', painel)
    checar(u"a face de entrada fica à vista nos dois trajetos (o valor que "
           u"vai ao servidor é o que a tela mostra)",
           m and u"hidden" not in m.group(1) and u"bo-ap-entrada-l" not in T.JS,
           m and m.group(0))
    velho = (u"el('bo-ap-trajeto').addEventListener('change', function(){ "
             u"el('bo-ap-entrada-l').hidden = (this.value !== 'cego') });")
    checar(u"(isca) a linha antiga, que escondia a entrada no aberto, seria "
           u"acusada", u"bo-ap-entrada-l" in velho)
    checar(u"a superfície da pele mostra o limiar usado",
           (u"limiar fixo de %d HU" % int(B.LIMIAR_HU)) in painel)
    checar(u"o resultado mostra o raio padrão e a face de entrada",
           u"linha('raio padrão'" in T.JS and u"linha('face de entrada'"
           in T.JS)
    m = re.search(r'<input type="checkbox" id="bo-ap-ato"[^>]*>', p)
    checar(u"a caixa do ato do aplicador NASCE desmarcada",
           m and u"checked" not in m.group(0))
    m = re.search(r'<button[^>]*id="bo-ap-exp-ok"[^>]*>', p)
    checar(u"e o botão de exportar nasce desligado",
           m and u"disabled" in m.group(0))
    checar(u"as duas frases do ato estão na janela",
           T._esc(A.FRASE_DO_ATO) in p and T._esc(A.FRASE_DA_CURVA) in p)
    checar(u"a frase vai ao servidor pela constante (o JSON da tela)",
           json.dumps(A.FRASE_DO_ATO) in T.dados_do_aplicador_para_o_js())
    checar(u"a janela de exportação mostra os parâmetros, os alertas e as "
           u"exigências", all(x in p for x in (
               u'id="bo-ap-params"', u'id="bo-ap-alertas"',
               u'id="bo-ap-exig"')))
    ui = io.open(_componentes.fonte("app/radai_ui.py"),
                 encoding="utf-8").read()
    checar(u"o brilho de processamento é o da casca, que segura 2 s (C3)",
           u"window.uiCarregando(alvo, true" in T.JS
           and u"window.uiCarregando(alvo, false)" in T.JS
           and u"UI_CARREGANDO_MINIMO_MS = 2000" in ui)
    checar(u"e liga nas duas gerações (bólus e aplicador)",
           T.JS.count(u"var apaga = brilho(") == 2)
    checar(u"o campo culpado treme pelo ajudante da casca (C3)",
           u"window.uiTremer(" in T.JS and u"window.uiTremer = function" in ui
           and u"if(d.campo) tremerCampo(d.campo)" in T.JS)
    faltam = [c for c in (u"canal_mm", u"espacamento_mm", u"distancia_mm",
                          u"corpo_mm", u"diametro_externo_mm", u"raio",
                          u"eixo") if (c + u": 'bo-ap-") not in T.JS]
    checar(u"todo campo que o motor acusa tem para onde tremer", not faltam,
           faltam)
    verdes = re.findall(r'<button[^>]*class="bo-bt(?: [^"]*)?"[^>]*>', p)
    checar(u"todo botão verde tem o reflexo da casca (%d)" % len(verdes),
           verdes and all(u"ui-verde" in b for b in verdes), verdes[:2])
    fonte = io.open(_componentes.fonte("app/radai_bolus_screen.py"),
                    encoding="utf-8").read()
    checar(u"a tela não usa mais o módulo da demo",
           u"radai_demo" not in fonte and u"bo-demo" not in fonte
           and u"boDemo" not in fonte)
    glifos = [g for g in u"◧◑⌇◎◒⇥✓✗↑" if g in fonte]
    checar(u"sem glifo Unicode de ícone na tela, nem nas tabelas de resultado "
           u"(%s)" % u"".join(glifos), not glifos)
    checar(u"(isca) a mesma busca acha o sinal de certo numa fonte que o tem",
           [g for g in u"✓✗↑" if g in u"linha('malha fechada', '✓')"])
    checar(u"a malha fechada diz sim ou não, e a seta das marcas é o SVG "
           u"«acima» da casca", T.JS.count(u"? 'sim' : 'não'") == 3
           and u"d.marcas.letra + ' ' + SETA" in T.JS
           and json.dumps(radai_ui.icone(u"acima")).replace(
               u"</", u"<\\/") in p and radai_ui.icone(u"acima"))
    cab = p.split(u"</header>")[0]
    checar(u"o ícone da cabeça é o SVG «camadas» da casca (TEL-19)",
           T.ICONE_DO_MODULO == u"camadas" and u'<span class="ui-fn-ic" '
           u'aria-hidden="true"><svg' in cab)
    checar(u"o JS não fecha o bloco de script por dentro",
           u"</script" not in T.JS.lower()
           and u"</script" not in T.dados_do_aplicador_para_o_js().lower())


def main():
    print(u"=" * 68)
    print(u"test_bolus_aplicador | o aplicador de superfície: canais, curva, "
          u"ato")
    print(u"=" * 68)
    os.environ["RADAI_CALIB_DIR"] = _cleanup.temporaria(
        "radai_teste_aplicador_acervo_")
    for f in (teste_padroes_e_menus, teste_parametros, teste_curvatura,
              teste_cruzamento):
        f()
    t0 = time.time()
    s = B.abrir(cilindro(), "CT")
    print(u"\n         · cilindro de 80 mm aberto em %.1f s" % (time.time() - t0))
    teste_pele_subvoxel(s)
    r_verde = teste_gerar_cilindro(s)
    s_peq, cx_peq, r_amarelo = teste_curva_amarela_e_piso()
    teste_face_de_entrada(s_peq, cx_peq)
    teste_fundo_cego(s)
    teste_descartados(s)
    teste_recusa_diz_por_que(s)
    teste_buraco_no_meio()
    teste_os_dois_eixos(s)
    teste_automatico_procura_eixo_seguro()
    teste_fundo_cego_sem_pele_alem_do_fundo(s)
    teste_caixa_sugerida(s)
    teste_a_sugerida_que_vira_a_colocacao_e_dita(s)
    teste_borda_por_volume_parcial()
    teste_raio_no_domo()
    teste_ficha_e_pacote(r_verde, r_amarelo)
    teste_ato(r_verde, r_amarelo)
    teste_rotas(s, s_peq, cx_peq)
    teste_tela()
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
