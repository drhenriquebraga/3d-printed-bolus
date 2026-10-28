# -*- coding: utf-8 -*-
import io
import math
import time
import zipfile

import numpy as np

import radai_bolus as B


class RecusaDoCampo(B.Recusa):

    def __init__(self, mensagem, campo=None):
        B.Recusa.__init__(self, mensagem)
        self.campo = campo


class Bloqueio(RecusaDoCampo):

    def __init__(self, mensagem, detalhe=None, campo=None):
        RecusaDoCampo.__init__(self, mensagem, campo)
        self.detalhe = dict(detalhe or {})


class ColocacaoVirou(Exception):

    def __init__(self, direcao):
        Exception.__init__(self, direcao)
        self.direcao = direcao


AFTERLOADERS = (
    {"chave": "microselectron_digital", "nome": u"microSelectron Digital",
     "piso_mm": 13.0, "conferido": True, "curta": u"ficha da Elekta",
     "fonte": u"Ficha técnica do fabricante (Elekta), levantada em "
              u"outubro de 2026."},
    {"chave": "flexitron", "nome": u"Flexitron", "piso_mm": 17.0,
     "conferido": True, "curta": u"ficha da Elekta",
     "fonte": u"Ficha técnica do fabricante (Elekta), levantada em "
              u"outubro de 2026."},
    {"chave": "gammamed_ix", "nome": u"GammaMed iX", "piso_mm": 13.0,
     "conferido": True, "curta": u"ficha da Varian",
     "fonte": u"Ficha técnica do fabricante (Varian), levantada em "
              u"outubro de 2026."},
    {"chave": "bravos", "nome": u"Bravos", "piso_mm": 13.0, "conferido": True,
     "curta": u"ficha da Varian",
     "fonte": u"Ficha técnica do fabricante (Varian), levantada em "
              u"outubro de 2026."},
    {"chave": "varisource_ix", "nome": u"VariSource iX", "piso_mm": 17.0,
     "conferido": False,
     "curta": u"número NÃO conferido",
     "fonte": u"Número achado só em trecho de busca, NÃO conferido na ficha "
              u"do fabricante (Varian). Até o físico conferir na instrução "
              u"de uso, vale 17 mm, o mesmo de «outro ou não sei»."},
    {"chave": "nao_sei", "nome": u"outro ou não sei", "piso_mm": 17.0,
     "conferido": True, "curta": u"o maior piso levantado",
     "fonte": u"O maior piso entre os fabricantes levantados, até o físico "
              u"conferir na instrução de uso do equipamento."},
)

CATETERES = (
    {"chave": "6f", "nome": u"tubo flexível 6F", "diametro_mm": 2.0,
     "piso_mm": 15.0, "curta": u"Licher 2025",
     "fonte": u"6F são 2,0 mm de diâmetro externo (1F = 1/3 mm). É o tubo "
              u"usado em canal impresso por Bielęda 2022 e Licher 2025, e o "
              u"raio mínimo de dobra de 15 mm é o que Licher 2025 dá para "
              u"ele; confira na instrução de uso do seu cateter."},
    {"chave": "proguide", "nome": u"ProGuide com obturador",
     "diametro_mm": 2.0, "piso_mm": 35.0, "curta": u"Laan 2019",
     "fonte": u"Agulha com obturador: abaixo de 35 mm ela flambou num canal "
              u"impresso, e a força de inserção só para de mudar a partir de "
              u"50 mm (Laan 2019). O diâmetro de 2,0 mm é o "
              u"do 6F: se o seu for de outro calibre, escolha «outro» e "
              u"digite o diâmetro externo."},
    {"chave": "outro", "nome": u"outro", "diametro_mm": None, "piso_mm": 35.0,
     "curta": u"o piso mais alto da pesquisa",
     "fonte": u"Sem número publicado para ele: vale o piso mais alto da "
              u"pesquisa (35 mm), até o físico conferir na instrução de uso. "
              u"Digite o diâmetro externo."},
)

RAIO_PADRAO_MM = 35.0
RAIO_FORCA_ESTAVEL_MM = 50.0

DIAMETRO_6F_MM = 2.0
FOLGA_PADRAO_MM = 1.0
FOLGA_SEM_ALERTA_MM = 0.6
CANAL_PADRAO_MM = DIAMETRO_6F_MM + FOLGA_PADRAO_MM
DISTANCIA_PADRAO_MM = 5.0
ESPACAMENTO_PADRAO_MM = 10.0
CORPO_PADRAO_MM = 10.0

FAIXAS = {
    "diametro_externo_mm": (0.5, 6.0),
    "canal_mm": (1.0, 8.0),
    "distancia_mm": (2.0, 15.0),
    "espacamento_mm": (4.0, 40.0),
    "corpo_mm": (4.0, 30.0),
    "raio_padrao_mm": (RAIO_PADRAO_MM, 100.0),
}

PAREDE_MIN_MM = 1.0
FUNIL_MM = 1.0
FUNIL_COMPRIMENTO_MM = 5.0
FUNDO_CEGO_PAREDE_MM = 2.0
PASSO_DO_PERFIL_MM = 0.25
PASSO_DA_LINHA_MM = 0.5
VIZINHO_DA_CURVATURA_MM = 1.0
SUAVE_DA_LINHA_MM = 5.0
INCLINACAO_MAX_GRAUS = 70.0
JANELA_DO_REFINO_MM = 3.0
FALHA_DO_REFINO_MAX = 0.10
FALHA_DO_REFINO_MAX_MM = 5.0
DESVIO_DA_PELE_AVISO_MM = 0.5
MEDIDAS_POR_CANAL = 200
LARGURA_BOA_DA_TRANSICAO = 3.0
FOLGA_DA_MELHOR_LARGURA = 1.5
MEIA_JANELA_MAX = 4
PUREZA_DA_REFERENCIA = 0.1
CONTRASTE_MIN_HU = 300.0
BLOCO_DA_PELE = 20000
MARGEM_DA_SUGERIDA_MM = 1.0
SUGERIDA_DESCARTADA = (u"Sem caixa sugerida: na caixa aparada em que os "
                       u"canais caberiam, a colocação automática mudaria de "
                       u"direção. Fixe a colocação no formulário e gere de "
                       u"novo para ver a sugestão nela.")

TRAJETOS = ("aberto", "cego")
ENTRADAS = ("inicio", "fim")
EIXOS = (("auto", None, u"automática"),
         ("ll", 0, u"laterolateral (direita–esquerda)"),
         ("ap", 1, u"anteroposterior"),
         ("cc", 2, u"craniocaudal"))
LADOS = {0: (u"direita", u"esquerda"), 1: (u"anterior", u"posterior"),
         2: (u"inferior", u"superior")}
DIRECAO_POR_EXTENSO = {"ant": u"anterior", "post": u"posterior",
                       "dir": u"direita", "esq": u"esquerda",
                       "sup": u"superior", "inf": u"inferior"}

CABECALHO_STL = (b"RadAI SURFACE APPLICATOR | DRAFT UNAPPROVED | physics+MD "
                 b"review | mm LPS")

ALERTA = (u"Acessório de tratamento: um canal mal desenhado pode prender o "
          u"cateter ou deslocar a posição de parada da fonte. O app não gera "
          u"o que sabidamente danifica a braquiterapia, alerta no resto, e "
          u"nada sai aprovado.")

EXIGENCIAS = (
    u"Rascunho sujeito a revisão física e médica: nada neste aplicador está "
    u"aprovado.",
    u"Antes de tratar: segunda TC com o aplicador posto, e plano novo feito "
    u"sobre ela.",
    u"Teste de passagem com o cabo de checagem (dummy) em cada canal, e o "
    u"pré-plano rodado no afterloader.",
    u"Dosimetria (filme ou equivalente) no comissionamento.",
)
EXIGENCIAS_DA_CURVA = (
    u"Curva amarela: conferência radiográfica das posições de parada no "
    u"trecho curvo.",
    u"Curva amarela: nenhuma parada ativa dentro da curva.",
    u"Curva amarela: conferência da instrução de uso do cateter.",
    u"Curva amarela: conferência da instrução de uso do afterloader.",
)

FRASE_DO_ATO = (u"Declaro que este aplicador é um rascunho sujeito a revisão "
                u"física e médica, que nada nele está aprovado, e que antes "
                u"de qualquer uso haverá segunda TC com o aplicador e plano "
                u"novo, teste de passagem com o cabo de checagem em cada "
                u"canal, pré-plano rodado no afterloader e dosimetria no "
                u"comissionamento.")
FRASE_DA_CURVA = (u"Declaro também que, no trecho curvo, as posições de "
                  u"parada serão conferidas por radiografia, que nenhuma "
                  u"parada ativa ficará dentro da curva, e que as instruções "
                  u"de uso do cateter e do afterloader serão conferidas.")

AVISO_BIOMETRIA = (u"A face interna deste aplicador é a superfície da pele "
                   u"do paciente. Num aplicador de cabeça ou face, o arquivo "
                   u"é uma biometria: trate-o como dado de paciente.")

AVISO_FUNDO_CEGO = (u"Fundo cego: nenhum dos seis artigos descreve nem testa "
                    u"canal cego, e o único que fala do assunto o evita de "
                    u"propósito. Confira o teste de passagem e a posição da "
                    u"primeira parada com cuidado redobrado.")

PROPOSTAS = (
    u"um arco maior: mude a caixa para uma região de curva mais aberta, ou "
    u"troque a direção dos canais;",
    u"um corpo mais espesso, com o canal mais longe da pele: sobre pele "
    u"convexa, a curva do canal abre;",
    u"dois canais no lugar de um, cada um num trecho mais reto;",
    u"encerrar o canal antes da curva: encurte a caixa na direção dos canais.",
)

REFERENCIAS = (
    u"Poltorak et al. J Contemp Brachytherapy 2024;16(2):156–169. "
    u"DOI 10.5114/jcb.2024.137357",
    u"Bellis et al. J Contemp Brachytherapy 2021;13(4):468–482. "
    u"DOI 10.5114/jcb.2021.108602",
    u"Bielęda et al. J Contemp Brachytherapy 2022;14(2):205–214. "
    u"DOI 10.5114/jcb.2022.114353",
    u"Ricotti et al. Physica Medica 2016. DOI 10.1016/j.ejmp.2016.08.016",
    u"Douglass e Caraça Santos. Brachytherapy 2019. "
    u"DOI 10.1016/j.brachy.2019.05.006",
    u"Jones et al. Brachytherapy 2017. DOI 10.1016/j.brachy.2016.11.003",
)
PESQUISA_DE_CURVATURA = (
    u"Laan et al. 3D Printing in Medicine 2019 (agulha com obturador em "
    u"canal impresso: 35 e 50 mm). DOI 10.1186/s41205-019-0047-x",
    u"Licher et al. Strahlentherapie und Onkologie 2025 (tubo 6F, raio "
    u"mínimo de dobra de 15 mm). DOI 10.1007/s00066-025-02372-5",
    u"Stern e Liu. J Appl Clin Med Phys 2010 (posições de parada no anel "
    u"curvo, conferidas por autorradiografia). DOI 10.1120/jacmp.v11i4.3158",
    u"Os pisos dos afterloaders vêm das fichas técnicas da Elekta e da "
    u"Varian, medidos numa curva só, plana e favorável.",
)


MATERIAL = (u"PLA e ABS se comportam como água no Ir-192, inclusive com "
            u"preenchimento baixo; o paciente é tratado com o mesmo padrão de "
            u"preenchimento do controle de qualidade; material sem "
            u"certificado pede filme ou campo entre a pele e a peça; "
            u"autoclave empena a peça.")
MATERIAL_REFERENCIAS = u"Referências: Bellis 2021 (tabela 2) e Ricotti 2016."

AJUDA = {
    "aplicador": (
        u"Aplicador de superfície para braquiterapia: um corpo impresso "
        u"sobre a pele, com canais paralelos que guiam os cateteres. A fonte "
        u"não passa pelo molde: ela corre dentro do cateter. Só aplicador de "
        u"superfície.",
        u"O desenho: a caixa marca a região, como no bólus; o corpo é uma "
        u"camada sobre a pele; os canais correm paralelos, na direção "
        u"escolhida, acompanhando a pele à distância pedida, e saem pelas "
        u"duas faces da caixa.",
        u"O app não gera o que sabidamente danifica a braquiterapia: curva "
        u"abaixo do piso do equipamento, canais que se cruzam, canal mais "
        u"estreito que o cateter. No resto, alerta. A exportação é por ato "
        u"declarado e sai com uma ficha.",
        u"Referências (conferidas na origem): " + u"; ".join(
            [u"Poltorak 2024", u"Bellis 2021", u"Bielęda 2022",
             u"Ricotti 2016", u"Douglass e Caraça Santos 2019",
             u"Jones 2017"]) + u"; e, da curvatura, Laan 2019, Licher 2025 "
        u"e Stern e Liu 2010. A lista completa, com o DOI, vai na ficha.",
    ),
    "afterloader": tuple(
        [u"O afterloader define o menor raio que a fonte atravessa. Piso de "
         u"cada um — abaixo dele o app não gera:"]
        + [u"%s: %d mm. %s" % (a["nome"], int(a["piso_mm"]), a["fonte"])
           for a in AFTERLOADERS]
        + [u"Os números de fabricante são medidos numa curva só, plana e "
           u"favorável; o aplicador tem curvas em 3D, uma depois da outra. "
           u"Por isso o padrão é 35 mm para todos."]),
    "cateter": tuple(
        [u"O cateter também tem piso, e vale o maior entre ele e o do "
         u"afterloader:"]
        + [u"%s: %d mm. %s" % (c["nome"], int(c["piso_mm"]), c["fonte"])
           for c in CATETERES]),
    "raio": (
        u"Raio padrão do canal: abaixo dele a curva é amarela. O sugerido é "
        u"35 mm, para todos os equipamentos: abaixo disso a agulha "
        u"intersticial com obturador flambou num canal impresso, e 50 mm é "
        u"onde a força de inserção para de mudar (Laan 2019, que mediu "
        u"canais de 20 a 75 mm).",
        u"O físico pode subir o padrão, por exemplo para 50 mm, e a curva "
        u"amarela passa a valer até ele. Abaixo de 35 mm o campo não desce: "
        u"ali a curva é sempre amarela, com as quatro exigências e a segunda "
        u"declaração, e abaixo do piso do equipamento o app não gera.",
        u"Os números de fabricante (13 a 17 mm) são medidos numa curva só, "
        u"plana e favorável; o aplicador tem curvas em 3D, em sequência.",
        u"Abaixo do piso do equipamento o app não gera, e propõe "
        u"alternativas. Entre o piso e o padrão gera, com alerta amarelo e "
        u"quatro exigências na ficha. A curvatura é medida na linha central "
        u"do canal, reamostrada a cada %s mm, e não só nos vértices do "
        u"STL." % (u"%.1f" % PASSO_DA_LINHA_MM).replace(u".", u","),
    ),
    "od": (
        u"Só para o cateter «outro»: o diâmetro externo, em mm, da instrução "
        u"de uso do cateter. 6F são 2,0 mm (1F = 1/3 mm).",
        u"O canal sugerido é esse diâmetro + 1,0 mm, e o app não gera canal "
        u"mais estreito que ele; o diâmetro do canal também é medido de "
        u"volta na malha.",
    ),
    "direcao": (
        u"O lado do paciente sobre o qual o aplicador assenta: o corpo cresce "
        u"da pele para fora nessa direção, e os canais não podem correr "
        u"nela.",
        u"Automática: o app escolhe o lado em que a face da caixa tem menos "
        u"corpo e a face oposta tem mais, isto é, por onde a caixa sai da "
        u"pele. Confira na prévia.",
    ),
    "superficie": (
        u"A pele que o desenho usa é a do limiar fixo de %d HU, a mesma do "
        u"bólus: a face interna da peça segue o ponto em que a TC cruza esse "
        u"valor, entre dois voxels. A distância do canal até a pele e a curva "
        u"do canal seguem a borda medida pelo volume parcial dos voxels desse "
        u"cruzamento, que não oscila com a posição da pele entre os cortes."
        % int(B.LIMIAR_HU),
        u"A janela da TC muda a pele percebida em 1 a 2 mm (Bellis); "
        u"Bielęda desenhou na janela de pulmão porque a de partes moles "
        u"deixou o aplicador apertado.",
        u"Os botões de janela do MPR (pele, partes moles, osso) só mudam a "
        u"exibição: a pele do desenho é sempre a de %d HU, qualquer que seja "
        u"a janela na tela." % int(B.LIMIAR_HU),
    ),
    "canal": (
        u"Padrão: o diâmetro externo do cateter + 1,0 mm (6F → 3,0 mm), a "
        u"folga com uso clínico publicado: o tubo 6F num canal de 3 mm, em "
        u"Bielęda 2022 e Licher 2025.",
        u"Folga abaixo de 0,6 mm só com uma peça de calibração impressa "
        u"antes, no mesmo filamento e na mesma impressora: o furo sai "
        u"diferente do desenho. Canal mais estreito que o cateter não é "
        u"gerado. O diâmetro é medido de volta na malha.",
    ),
    "distancia": (
        u"5 mm entre o eixo do canal e a pele: a recomendação do GEC-ESTRO "
        u"que Bellis 2021 cita, e o caminho da fonte de Bielęda 2022. A "
        u"distância é medida de volta na linha do canal, e vai à ficha.",
    ),
    "espacamento": (
        u"10 mm entre canais: os do aplicador comercial de Freiburg, contra "
        u"o qual Bellis 2021 e Ricotti 2016 comparam; Bielęda usou 5 a 7 mm. "
        u"Canais que se cruzam, ou com parede menor que 1 mm entre eles, não "
        u"são gerados.",
    ),
    "corpo": (
        u"10 mm de espessura: o corpo de 1 cm de Bielęda 2022. O corpo "
        u"é uma camada sobre a pele, como o bólus anatômico, e o canal fica "
        u"dentro dela com pelo menos 1 mm de parede dos dois lados.",
    ),
    "eixo": (
        u"Os canais correm paralelos entre si, nesta direção, e acompanham a "
        u"pele: a curva de cada canal é a da pele naquela linha, suavizada "
        u"em %d mm, e é medida inteira. Automática: o app traça as duas "
        u"direções perpendiculares à colocação e fica com a que acomoda mais "
        u"canais; no empate, craniocaudal, ou laterolateral quando a "
        u"colocação é superior ou inferior." % int(SUAVE_DA_LINHA_MM),
    ),
    "trajeto": (
        u"Aberto: o canal atravessa o corpo de face a face, e a ponta e o "
        u"conector do cateter saem do corpo (Bielęda, de propósito, «not "
        u"blind-ended»).",
        u"Fundo cego é opção, com alerta: nenhum dos seis artigos descreve "
        u"nem testa canal cego, e o único que fala do assunto o evita de "
        u"propósito.",
    ),
    "entrada": (
        u"A face por onde o cateter entra no aplicador. O início do eixo é a "
        u"direita, o anterior ou o inferior do paciente; o fim, o lado "
        u"oposto.",
        u"No trajeto aberto o canal sai nas duas faces e a peça é a mesma: a "
        u"escolha diz de qual face a ficha conta as distâncias ao longo do "
        u"canal (o raio mínimo e os trechos de curva amarela). No fundo "
        u"cego, é a única face aberta.",
    ),
    "funil": (
        u"A boca do canal abre 1 mm de raio a mais, ao longo de 5 mm: o "
        u"desvio do cateter é maior na boca do canal (Harris, citado por "
        u"Bellis). A medida do funil é escolha geométrica deste app, e não "
        u"da literatura.",
    ),
    "material": (MATERIAL, MATERIAL_REFERENCIAS),
}


def _por_chave(tabela, chave, nome):
    for item in tabela:
        if item["chave"] == chave:
            return item
    raise B.Recusa(u"%s desconhecido: %s." % (nome, str(chave)[:40]))


def padroes():
    return {"afterloader": "nao_sei", "cateter": "6f",
            "diametro_externo_mm": DIAMETRO_6F_MM,
            "canal_mm": CANAL_PADRAO_MM,
            "distancia_mm": DISTANCIA_PADRAO_MM,
            "espacamento_mm": ESPACAMENTO_PADRAO_MM,
            "corpo_mm": CORPO_PADRAO_MM, "raio_padrao_mm": RAIO_PADRAO_MM,
            "eixo": "auto", "trajeto": "aberto",
            "entrada": "inicio", "funil": True, "direcao": "auto"}


def _numero(valor, chave, rotulo):
    lo, hi = FAIXAS[chave]
    try:
        v = float(valor)
    except Exception:
        raise RecusaDoCampo(u"%s: não é um número." % rotulo, chave)
    if not math.isfinite(v) or not (lo <= v <= hi):
        raise RecusaDoCampo(u"%s fora da faixa: de %s a %s mm."
                            % (rotulo, _mm(lo), _mm(hi)), chave)
    return v


def _mm(v, casas=1):
    if v is None or not math.isfinite(float(v)):
        return u"—"
    return (u"%.*f" % (casas, float(v))).replace(u".", u",")


RAIO_RETO_MM = 1000.0


def _raio_txt(v):
    if v is None or not math.isfinite(float(v)) or float(v) >= RAIO_RETO_MM:
        return u"sem curva (reto)"
    return u"%s mm" % _mm(v)


def limiar_amarelo(padrao_mm):
    # GUARDA: abaixo de RAIO_PADRAO_MM a curva e sempre amarela, qualquer que seja o padrao recebido.
    try:
        p = float(padrao_mm)
    except Exception:
        p = RAIO_PADRAO_MM
    if not math.isfinite(p):
        p = RAIO_PADRAO_MM
    return max(p, RAIO_PADRAO_MM)


def curva_e_amarela(raio_min_mm, padrao_mm):
    try:
        r = float(raio_min_mm)
    except Exception:
        return False
    return math.isfinite(r) and r < limiar_amarelo(padrao_mm)


def conferir_parametros(parametros=None):
    q = padroes()
    for k, v in (parametros or {}).items():
        if k in q and v is not None and v != u"":
            q[k] = v
    al = _por_chave(AFTERLOADERS, q["afterloader"], u"Afterloader")
    ca = _por_chave(CATETERES, q["cateter"], u"Cateter")
    if ca["diametro_mm"] is None:
        od = _numero(q["diametro_externo_mm"], "diametro_externo_mm",
                     u"Diâmetro externo do cateter")
    else:
        od = float(ca["diametro_mm"])
    canal = _numero(q["canal_mm"], "canal_mm", u"Diâmetro do canal")
    d = _numero(q["distancia_mm"], "distancia_mm",
                u"Distância do eixo do canal à pele")
    s = _numero(q["espacamento_mm"], "espacamento_mm",
                u"Espaçamento entre canais")
    T = _numero(q["corpo_mm"], "corpo_mm", u"Espessura do corpo")
    if q["trajeto"] not in TRAJETOS:
        raise B.Recusa(u"Trajeto desconhecido: %s." % str(q["trajeto"])[:20])
    if q["entrada"] not in ENTRADAS:
        raise B.Recusa(u"Lado da entrada desconhecido: %s."
                       % str(q["entrada"])[:20])
    if q["eixo"] not in [e[0] for e in EIXOS]:
        raise B.Recusa(u"Direção dos canais desconhecida: %s."
                       % str(q["eixo"])[:20])
    if q["direcao"] not in ("auto",) + B.DIRECOES:
        raise B.Recusa(u"Direção de colocação desconhecida: %s."
                       % str(q["direcao"])[:20])
    funil = q["funil"] is True
    r = canal / 2.0
    r_f = r + (FUNIL_MM if funil else 0.0)
    folga = canal - od
    if folga < 0:
        raise Bloqueio(
            u"Canal de %s mm é mais estreito que o cateter de %s mm: o "
            u"cateter não passa, e o aplicador não é gerado. O padrão é o "
            u"diâmetro externo + %s mm." % (_mm(canal), _mm(od),
                                             _mm(FOLGA_PADRAO_MM)),
            {"motivo": "canal_estreito", "canal_mm": canal, "cateter_mm": od},
            "canal_mm")
    if d - r_f < PAREDE_MIN_MM:
        raise RecusaDoCampo(
            u"Com o canal de %s mm%s a %s mm da pele, sobram %s mm de parede "
            u"entre o canal e a pele, e o mínimo é %s mm. Afaste o canal da "
            u"pele ou estreite o canal." % (
                _mm(canal), u" (e o funil)" if funil else u"", _mm(d),
                _mm(d - r_f), _mm(PAREDE_MIN_MM)), "distancia_mm")
    if T - d - r_f < PAREDE_MIN_MM:
        raise RecusaDoCampo(
            u"Corpo de %s mm fino demais: com o canal a %s mm da pele, sobram "
            u"%s mm de parede por fora, e o mínimo é %s mm. Engrosse o "
            u"corpo ou aproxime o canal da pele."
            % (_mm(T), _mm(d), _mm(T - d - r_f), _mm(PAREDE_MIN_MM)),
            "corpo_mm")
    if s - 2.0 * r_f < PAREDE_MIN_MM:
        raise Bloqueio(
            u"Com %s mm entre canais de %s mm%s, os canais se cruzariam (a "
            u"parede entre eles seria de %s mm, e o mínimo é %s mm). "
            u"Aumente o espaçamento." % (
                _mm(s), _mm(canal), u" com funil" if funil else u"",
                _mm(s - 2.0 * r_f), _mm(PAREDE_MIN_MM)),
            {"motivo": "canais_cruzam", "espacamento_mm": s},
            "espacamento_mm")
    piso = max(al["piso_mm"], ca["piso_mm"])
    try:
        pedido = float(q["raio_padrao_mm"])
    except Exception:
        pedido = None
    if pedido is not None and math.isfinite(pedido) and \
            pedido < RAIO_PADRAO_MM:
        raise RecusaDoCampo(
            u"Raio padrão de %s mm recusado: o padrão começa em %s mm e só "
            u"sobe. Abaixo de %s mm a curva é sempre amarela, com as quatro "
            u"exigências e a segunda declaração; abaixo do piso de %s mm (%s "
            u"com %s), o app não gera." % (
                _mm(pedido), _mm(RAIO_PADRAO_MM, 0), _mm(RAIO_PADRAO_MM, 0),
                _mm(piso, 0), al["nome"], ca["nome"]),
            "raio_padrao_mm")
    padrao = _numero(q["raio_padrao_mm"], "raio_padrao_mm",
                     u"Raio padrão do canal")
    if padrao < piso:
        raise RecusaDoCampo(
            u"Raio padrão de %s mm abaixo do piso de %s mm (%s com %s): o "
            u"padrão começa no maior entre o piso e %s mm, e só sobe."
            % (_mm(padrao), _mm(piso, 0), al["nome"], ca["nome"],
               _mm(RAIO_PADRAO_MM, 0)),
            "raio_padrao_mm")
    alertas = []
    if folga < FOLGA_SEM_ALERTA_MM:
        alertas.append(
            u"Folga de %s mm entre o canal e o cateter, abaixo de %s mm: só "
            u"com uma peça de calibração impressa antes, no mesmo filamento "
            u"e na mesma impressora (o furo sai diferente do desenho)."
            % (_mm(folga), _mm(FOLGA_SEM_ALERTA_MM)))
    if not al["conferido"]:
        alertas.append(u"%s: %s" % (al["nome"], al["fonte"]))
    if ca["diametro_mm"] is None:
        alertas.append(u"Cateter «outro»: o diâmetro externo de %s mm foi "
                       u"digitado, e o piso de %s mm é o mais alto da "
                       u"pesquisa. Confira os dois na instrução de uso."
                       % (_mm(od), _mm(ca["piso_mm"], 0)))
    if q["trajeto"] == "cego":
        alertas.append(AVISO_FUNDO_CEGO)
    return {"afterloader": al["chave"], "afterloader_nome": al["nome"],
            "afterloader_piso_mm": al["piso_mm"],
            "afterloader_fonte": al["fonte"],
            "afterloader_conferido": al["conferido"],
            "cateter": ca["chave"], "cateter_nome": ca["nome"],
            "cateter_piso_mm": ca["piso_mm"], "cateter_fonte": ca["fonte"],
            "diametro_externo_mm": od, "canal_mm": canal, "folga_mm": folga,
            "distancia_mm": d, "espacamento_mm": s, "corpo_mm": T,
            "eixo": q["eixo"], "trajeto": q["trajeto"],
            "entrada": q["entrada"], "funil": funil,
            "direcao": q["direcao"], "piso_mm": piso,
            "padrao_mm": padrao, "padrao_sugerido_mm": RAIO_PADRAO_MM,
            "raio_mm": r, "raio_funil_mm": r_f,
            "alertas": alertas}


def eixo_do_canal(eixo, direcao):
    an = B._NORMAL[direcao][0]
    if eixo in (None, "", "auto"):
        return 2 if an != 2 else 0
    ax = dict((e[0], e[1]) for e in EIXOS)[eixo]
    if ax == an:
        raise RecusaDoCampo(u"Os canais não podem correr na direção de "
                            u"colocação (%s): escolha outra direção para os "
                            u"canais." % DIRECAO_POR_EXTENSO.get(direcao,
                                                                 direcao),
                            "eixo")
    return ax


def eixos_do_canal(eixo, direcao):
    au = eixo_do_canal(eixo, direcao)
    if eixo in (None, "", "auto"):
        return [au, 3 - B._NORMAL[direcao][0] - au]
    return [au]


def nome_do_eixo(ax):
    for chave, a, nome in EIXOS:
        if a == ax:
            return nome
    return u"?"


def face_de_entrada(au, entrada):
    return LADOS[int(au)][0 if entrada == "inicio" else 1]


def reamostrar(pts, passo=PASSO_DA_LINHA_MM):
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    if len(p) < 2:
        return p.copy(), np.zeros(len(p))
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(p, axis=0),
                                                        axis=1))])
    n = int(math.floor(s[-1] / passo + 1e-9)) + 1
    si = np.arange(n) * float(passo)
    q = np.stack([np.interp(si, s, p[:, k]) for k in range(3)], axis=1)
    return q, si


def raios_de_curvatura(pts, passo=PASSO_DA_LINHA_MM,
                       vizinho_mm=VIZINHO_DA_CURVATURA_MM):
    q, s = reamostrar(pts, passo)
    k = max(1, int(round(float(vizinho_mm) / float(passo))))
    R = np.full(len(q), np.inf)
    if len(q) > 2 * k:
        a, b, c = q[:-2 * k], q[k:-k], q[2 * k:]
        ab = np.linalg.norm(b - a, axis=1)
        bc = np.linalg.norm(c - b, axis=1)
        ca = np.linalg.norm(a - c, axis=1)
        dobro_da_area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = ab * bc * ca / (2.0 * dobro_da_area)
        r[~np.isfinite(r) | (dobro_da_area < 1e-12)] = np.inf
        R[k:-k] = r
    return R, s, q


def trechos_abaixo(R, s, limite):
    abaixo = np.asarray(R) < float(limite)
    fora = []
    i, n = 0, len(abaixo)
    while i < n:
        if abaixo[i]:
            j = i
            while j + 1 < n and abaixo[j + 1]:
                j += 1
            fora.append((float(s[i]), float(s[j])))
            i = j + 1
        else:
            i += 1
    return fora


def _compensacao(h, r):
    return h * h / (4.0 * r)


def _suavizar(y, sigma):
    from scipy import ndimage
    y = np.asarray(y, dtype=np.float64)
    if sigma <= 0 or len(y) < 3:
        return y.copy()
    k = min(int(math.ceil(4.0 * sigma)), len(y) - 1)
    esq = 2.0 * y[0] - y[k:0:-1]
    dir_ = 2.0 * y[-1] - y[-2:-k - 2:-1]
    z = np.concatenate([esq, y, dir_])
    return ndimage.gaussian_filter1d(z, sigma, mode="nearest")[k:k + len(y)]


def _amostrar(campo, pts_mm, h):
    from scipy import ndimage
    p = np.asarray(pts_mm, dtype=np.float64).reshape(-1, 3) / h
    return ndimage.map_coordinates(campo, [p[:, 2], p[:, 1], p[:, 0]],
                                   order=1, mode="nearest")


def larguras_da_transicao(normais, esp):
    a = np.abs(np.asarray(normais, dtype=np.float64)) * np.asarray(
        esp, dtype=np.float64)[None, :]
    tot = a.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        w = 1.0 + 2.0 * (tot - a) / a
    w[~np.isfinite(w)] = np.inf
    return w


def borda_por_volume_parcial(hu, esp, off, pts, k, s, w):
    from scipy import ndimage
    esp = np.asarray(esp, dtype=np.float64)
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
    c = (np.asarray(off, dtype=np.float64)[None, :] + pts) / esp[None, :]
    K = np.ceil(c[:, k] - 1e-9) if s > 0 else np.floor(c[:, k] + 1e-9)
    R = MEIA_JANELA_MAX
    meia = np.minimum(R, np.ceil(np.asarray(w) / 2.0).astype(int) + 1)
    js = np.arange(-R - 2, R + 2)
    n = len(pts)
    coords = np.empty((3, n, len(js)))
    for ax in range(3):
        coords[2 - ax] = c[:, ax][:, None]
    coords[2 - k] = K[:, None] + s * js[None, :]
    v = ndimage.map_coordinates(hu, coords.reshape(3, -1), order=1,
                                mode="nearest", output=np.float64).reshape(
                                    n, len(js))
    del coords
    linhas = np.arange(n)
    ia, ib = R + 1 - meia, R + 2 + meia
    ar, tr = v[linhas, ia], v[linhas, ib]
    den = tr - ar
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.clip((v - ar[:, None]) / den[:, None], 0.0, 1.0)
    na_janela = (js[None, :] >= -meia[:, None]) & (js[None, :] < meia[:, None])
    ar_sobra = np.where(na_janela, 1.0 - f, 0.0).sum(axis=1)
    novo = (K - s * (meia + 0.5) + s * ar_sobra) * esp[k] - off[k]
    tol = PUREZA_DA_REFERENCIA * den
    # GUARDA: referencia que nao e plato puro, ou borda longe do cruzamento, fica no cruzamento linear.
    ok = (ar < B.LIMIAR_HU) & (tr >= B.LIMIAR_HU) & (den > CONTRASTE_MIN_HU)
    ok &= np.abs(v[linhas, ia - 1] - ar) <= tol
    ok &= np.abs(v[linhas, ib + 1] - tr) <= tol
    ok &= np.abs(novo - pts[:, k]) <= 0.5 * (np.asarray(w) + 1.0) * esp[k]
    return novo, ok


def _pele_por_volume_parcial(J, h, serie, off, pts, k, s):
    g = np.empty_like(pts)
    for ax in range(3):
        e = np.zeros(3)
        e[ax] = h
        g[:, ax] = _amostrar(J, pts + e, h) - _amostrar(J, pts - e, h)
    w = larguras_da_transicao(g, serie.esp)
    wk = w[:, k]
    fica = np.isfinite(wk) & (wk <= np.maximum(
        LARGURA_BOA_DA_TRANSICAO, FOLGA_DA_MELHOR_LARGURA * w.min(axis=1)))
    pts, wk = pts[fica], wk[fica]
    for i in range(0, len(pts), BLOCO_DA_PELE):
        bloco = pts[i:i + BLOCO_DA_PELE]
        novo, ok = borda_por_volume_parcial(serie.hu, serie.esp, off, bloco,
                                            k, s, wk[i:i + BLOCO_DA_PELE])
        bloco[ok, k] = novo[ok]
    return pts


def pontos_da_pele(J, corpo, h, serie=None, off=None):
    fora = []
    for eixo in range(3):
        a = [slice(None)] * 3
        b = [slice(None)] * 3
        a[eixo], b[eixo] = slice(0, -1), slice(1, None)
        a, b = tuple(a), tuple(b)
        Ja, Jb = J[a], J[b]
        for de_dentro, ja_m, jb_m, s in ((corpo[a] & (Jb < 0), Ja, Jb, -1),
                                         (corpo[b] & (Ja < 0), Jb, Ja, 1)):
            idx = np.nonzero(de_dentro)
            if not idx[0].size:
                continue
            ja = ja_m[idx].astype(np.float64)
            jb = jb_m[idx].astype(np.float64)
            t = np.clip(ja / (ja - jb), 0.0, 1.0)
            zyx = np.stack(idx, axis=1).astype(np.float64)
            if ja_m is Jb:
                zyx[:, eixo] += 1.0
                t = -t
            zyx[:, eixo] += t
            pts = zyx[:, ::-1] * h
            if serie is not None:
                pts = _pele_por_volume_parcial(J, h, serie, off, pts,
                                               2 - eixo, s)
            fora.append(pts)
    if not fora:
        return np.zeros((0, 3))
    return np.concatenate(fora)


def _maior_sequencia(v):
    maior = atual = 0
    for x in np.asarray(v, dtype=bool):
        atual = atual + 1 if x else 0
        maior = max(maior, atual)
    return maior


def _refinar_na_pele(perfil, us, v, au, an, av, sn, h, arvore, d):
    w = max(2.0 * h, JANELA_DO_REFINO_MM)
    janela = np.arange(-w, w + 1e-9, 0.1)
    passos = perfil[:, None] + sn * janela[::-1][None, :]
    pts = np.empty(passos.shape + (3,))
    pts[..., au] = us[:, None]
    pts[..., an] = passos
    pts[..., av] = v
    dk = arvore.query(pts.reshape(-1, 3))[0].reshape(passos.shape)
    abaixo = dk <= d
    tem = abaixo.any(axis=1)
    m = np.argmax(abaixo, axis=1)
    ok = tem & (m > 0)
    linhas = np.arange(len(us))
    m0 = np.maximum(m - 1, 0)
    D0, D1 = dk[linhas, m0], dk[linhas, m]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(np.abs(D0 - D1) > 1e-12, (D0 - d) / (D0 - D1), 0.0)
    t = np.clip(t, 0.0, 1.0)
    novo = passos[linhas, m0] + t * (passos[linhas, m] - passos[linhas, m0])
    return np.where(ok, novo, perfil), ok


def causas_do_trajeto(tem, m, bloq_m, du):
    tem = np.asarray(tem, dtype=bool)
    m = np.asarray(m)
    bloq_m = np.asarray(bloq_m, dtype=bool)
    sem_pele = ~tem
    topo = tem & (m == 0)
    objeto = tem & (m > 0) & bloq_m
    invalido = sem_pele | topo | objeto
    meio = len(tem) // 2
    passos = {"sem_pele_passos": int(sem_pele.sum()),
              "topo_passos": int(topo.sum()),
              "objeto_passos": int(objeto.sum()),
              "validos_passos": int((~invalido).sum()),
              "inicio_passos": int(invalido[:meio].sum()),
              "fim_passos": int(invalido[meio:].sum()),
              "sem_pele_inicio_passos": int(sem_pele[:meio].sum()),
              "sem_pele_fim_passos": int(sem_pele[meio:].sum())}
    passos.update({
        "sem_pele_mm": passos["sem_pele_passos"] * float(du),
        "topo_mm": passos["topo_passos"] * float(du),
        "objeto_mm": passos["objeto_passos"] * float(du),
        "invalido_mm": int(invalido.sum()) * float(du),
        "inicio_mm": passos["inicio_passos"] * float(du),
        "fim_mm": passos["fim_passos"] * float(du),
        "sem_pele_inicio_mm": passos["sem_pele_inicio_passos"] * float(du),
        "sem_pele_fim_mm": passos["sem_pele_fim_passos"] * float(du)})
    return passos


def _mm_para_fora(v):
    return int(math.ceil(float(v) - 1e-9)) if v > 0 else 0


def frase_das_causas(c, au, alvo_mm):
    partes = []
    if c.get("sem_pele_mm", 0) > 0:
        lado0, lado1 = LADOS[int(au)]
        a = _mm_para_fora(c["sem_pele_inicio_mm"])
        b = _mm_para_fora(c["sem_pele_fim_mm"])
        lados = [u"%d mm do lado %s" % (mm, lado)
                 for mm, lado in ((a, lado0), (b, lado1)) if mm]
        partes.append(u"falta pele sob o canal, dentro da faixa da caixa, em "
                      u"%d mm do trajeto (%s)" % (a + b, u" e ".join(lados)))
    if c.get("topo_mm", 0) > 0:
        partes.append(u"em %d mm a pele já está a menos de %s mm do topo da "
                      u"caixa: a caixa entra no corpo ou não sai da pele o "
                      u"bastante" % (_mm_para_fora(c["topo_mm"]),
                                     _mm(alvo_mm)))
    if c.get("objeto_mm", 0) > 0:
        partes.append(u"em %d mm há outro objeto acima da pele (mesa, apoio "
                      u"ou máscara) no caminho do canal"
                      % _mm_para_fora(c["objeto_mm"]))
    return u"; ".join(partes)


def _descarte_do_trajeto(k, v, tem, m, bloq_m, du, au, alvo_mm):
    c = causas_do_trajeto(tem, m, bloq_m, du)
    c.update({"k": int(k), "v_mm": float(v), "causa": "trajeto",
              "motivo": frase_das_causas(c, au, alvo_mm)})
    return c


def _melhor_descartado(descartados, n):
    centro = (n - 1) / 2.0
    return min(descartados, key=lambda x: (round(x.get("invalido_mm", 0.0), 6),
                                           abs(x.get("k", 0) - centro),
                                           x.get("k", 0)))


def _propostas_do_descarte(x, direcao, au, alvo_mm):
    if x.get("causa") == "refino":
        return [u"Confira na prévia se a pele sob a caixa está inteira e mude "
                u"a caixa, ou troque a direção dos canais."]
    if x.get("causa") == "inclinacao":
        return [u"Troque a direção dos canais, ou mude a caixa para uma região "
                u"em que a pele incline menos."]
    lado0, lado1 = LADOS[int(au)]
    lados = [l for l, mm in ((lado0, x.get("sem_pele_inicio_mm", 0)),
                             (lado1, x.get("sem_pele_fim_mm", 0))) if mm > 0]
    onde = (u"do lado %s" % lados[0]) if len(lados) == 1 else (
        u"dos dois lados (%s e %s)" % (lado0, lado1))
    cada = [
        (x.get("sem_pele_mm", 0),
         u"Encurte a caixa na direção dos canais, %s, para a pele ficar sob "
         u"todo o trajeto: o canal tem o comprimento da caixa e sai pelas "
         u"duas faces. Ou troque a direção dos canais." % onde),
        (x.get("topo_mm", 0),
         u"Afaste da pele a face %s da caixa: o topo da caixa precisa ficar a "
         u"mais de %s mm da pele em todo o trajeto."
         % (DIRECAO_POR_EXTENSO.get(direcao, direcao), _mm(alvo_mm))),
        (x.get("objeto_mm", 0),
         u"Um objeto acima da pele barra o canal, e o app não o ignora: a "
         u"peça pede uma TC sem o objeto na região, ou o objeto recortado "
         u"(decisão clínica)."),
    ]
    cada = [c for c in cada if c[0] > 0]
    cada.sort(key=lambda c: -c[0])
    return [c[1] for c in cada]


def frase_da_sugerida(sug):
    return (u"Caixa sugerida: %s mm na direção %s, em vez dos %s mm "
            u"desenhados, com %d %s nessa direção. Ela deixa de cobrir %s mm "
            u"da região desenhada: confira se o alvo continua dentro antes de "
            u"usá-la. A caixa só muda com o clique em «Usar a caixa "
            u"sugerida», e o aplicador só sai quando você gerar de novo." % (
                _mm(sug["mm"], 0), nome_do_eixo(sug["eixo_canal"]),
                _mm(sug["mm_desenhada"], 0), sug["canais"],
                u"canal" if sug["canais"] == 1 else u"canais",
                _mm(sug["mm_desenhada"] - sug["mm"], 0)))


def com_sugerida(e, outros=(), sugerida=None):
    det = dict(getattr(e, "detalhe", None) or {})
    resumo = det.get("resumo") or str(e)
    for o in outros or ():
        resumo += (u" Direção dos canais automática: na %s também não coube "
                   u"canal." % nome_do_eixo(o))
    propostas = list(det.get("propostas") or [])
    if sugerida and sugerida.get("descartada"):
        propostas.append(SUGERIDA_DESCARTADA)
        det["sugerida_descartada"] = {
            "colocacao": sugerida["colocacao"],
            "colocacao_na_sugerida": sugerida["colocacao_na_sugerida"],
            "sugerida_mm": float(sugerida["mm"]),
            "sugerida_eixo": int(sugerida["eixo_canal"])}
    elif sugerida:
        propostas.append(frase_da_sugerida(sugerida))
        det.update({"caixa_sugerida": dict(sugerida["caixa"]),
                    "sugerida_mm": float(sugerida["mm"]),
                    "sugerida_canais": int(sugerida["canais"]),
                    "sugerida_eixo": int(sugerida["eixo_canal"])})
    det.update({"resumo": resumo, "propostas": propostas})
    return Bloqueio(u" ".join([resumo] + propostas), det,
                    getattr(e, "campo", None))


def recusa_sem_canal(descartados, n, direcao, dir_auto, au, av, alvo_mm,
                     comprimento_mm):
    lado0, lado1 = LADOS[int(av)]
    cab = (u"Nenhum canal coube na caixa. Colocação %s (%s), canais na "
           u"direção %s: %d tentados." % (
               DIRECAO_POR_EXTENSO.get(direcao, direcao),
               u"escolhida pelo app" if dir_auto
               else u"escolhida no formulário", nome_do_eixo(au), n))
    if not descartados:
        resumo = cab
        return Bloqueio(resumo, {"motivo": "nenhum_canal", "resumo": resumo,
                                 "propostas": [], "canais_tentados": n})
    x = _melhor_descartado(descartados, n)
    quem = u"O melhor, o canal %d (contados do lado %s para o lado %s)" % (
        x["k"] + 1, lado0, lado1)
    a = _mm_para_fora(x.get("sem_pele_inicio_mm", 0))
    b = _mm_para_fora(x.get("sem_pele_fim_mm", 0))
    causas = {"sem_pele": a + b,
              "topo": _mm_para_fora(x.get("topo_mm", 0)),
              "objeto": _mm_para_fora(x.get("objeto_mm", 0)),
              "lado_inicio": a, "lado_fim": b}
    if x.get("causa") == "trajeto":
        comp = int(round(float(comprimento_mm)))
        falta = causas["sem_pele"] + causas["topo"] + causas["objeto"]
        corpo = u"%s, tem pele sob %d dos %d mm do trajeto; %s." % (
            quem, max(0, comp - falta), comp, x["motivo"])
    else:
        corpo = u"%s, tem pele sob todo o trajeto, mas %s." % (quem,
                                                              x["motivo"])
    resumo = cab + u" " + corpo
    propostas = _propostas_do_descarte(x, direcao, au, alvo_mm)
    return Bloqueio(
        resumo + u" " + u" ".join(propostas),
        {"motivo": "nenhum_canal", "resumo": resumo, "propostas": propostas,
         "colocacao": direcao, "colocacao_automatica": bool(dir_auto),
         "eixo_canal": int(au), "canais_tentados": int(n),
         "melhor_canal": int(x["k"]) + 1, "causa": x.get("causa"),
         "causas_mm": causas,
         "descartados": [dict(d) for d in descartados]})


def _lista_de_canais(ks):
    ks = sorted(int(k) + 1 for k in ks)
    if len(ks) == 1:
        return u"o canal %d" % ks[0]
    if len(ks) > 2 and ks[-1] - ks[0] == len(ks) - 1:
        return u"os canais %d a %d" % (ks[0], ks[-1])
    return u"os canais %s e %d" % (u", ".join(u"%d" % k for k in ks[:-1]),
                                   ks[-1])


def recusa_canal_no_meio(canais, descartados, n, direcao, au, av, alvo_mm,
                         comprimento_mm):
    aceitos = sorted(int(c["k"]) for c in canais)
    if len(aceitos) < 2:
        return None
    meio = sorted([x for x in descartados
                   if aceitos[0] < int(x.get("k", -1)) < aceitos[-1]],
                  key=lambda x: int(x["k"]))
    if not meio:
        return None
    lado0, lado1 = LADOS[int(av)]
    plural = len(meio) > 1
    x = meio[len(meio) // 2]
    cab = (u"Buraco no meio do aplicador: %s (dos %d tentados, contados do "
           u"lado %s para o lado %s) não %s, e há canais aceitos dos dois "
           u"lados (%s). O aplicador não é gerado: só com os canais das "
           u"bordas, o centro da área ficaria sem cateter, e isso é risco de "
           u"subcobertura do alvo." % (
               _lista_de_canais([m["k"] for m in meio]), n, lado0, lado1,
               u"couberam" if plural else u"coube", _lista_de_canais(aceitos)))
    quem = u"O canal %d%s" % (x["k"] + 1,
                              u", no meio do buraco," if plural else u"")
    if x.get("causa") == "trajeto":
        comp = int(round(float(comprimento_mm)))
        falta = (_mm_para_fora(x.get("sem_pele_inicio_mm", 0))
                 + _mm_para_fora(x.get("sem_pele_fim_mm", 0))
                 + _mm_para_fora(x.get("topo_mm", 0))
                 + _mm_para_fora(x.get("objeto_mm", 0)))
        corpo = u"%s tem pele sob %d dos %d mm do trajeto; %s." % (
            quem, max(0, comp - falta), comp, x["motivo"])
    else:
        corpo = u"%s tem pele sob todo o trajeto, mas %s." % (quem,
                                                             x["motivo"])
    resumo = cab + u" " + corpo
    propostas = _propostas_do_descarte(x, direcao, au, alvo_mm)
    return Bloqueio(
        resumo + u" " + u" ".join(propostas),
        {"motivo": "canal_no_meio", "resumo": resumo, "propostas": propostas,
         "canais_no_meio": [int(m["k"]) + 1 for m in meio],
         "canais_aceitos": [k + 1 for k in aceitos],
         "canal_citado": int(x["k"]) + 1, "causa": x.get("causa"),
         "canais_tentados": int(n),
         "descartados": [dict(d) for d in descartados]})


def trecho_exigido(i0, i1, u0, u1, du, P):
    if P["trajeto"] != "cego":
        return i0, i1
    fundo = P["raio_mm"] + FUNDO_CEGO_PAREDE_MM
    if P["entrada"] == "inicio":
        n = int(math.floor((u1 - fundo - u0) / du + 1e-9)) + 1
        return i0, max(i0 + 1, min(i1, i0 + n))
    n = int(math.ceil(fundo / du - 1e-9))
    return min(i1 - 1, max(i0, i0 + n)), i1


def _sem_ingreme(valido, D, m, ns, alvo, du):
    fora = valido.copy()
    w = np.concatenate([[False], valido, [False]]).astype(np.int8)
    d = np.diff(w)
    for a, b in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
        if b - a < 3:
            continue
        mm, m0 = m[a:b], np.maximum(m[a:b] - 1, 0)
        k = np.arange(b - a)
        D0, D1 = D[a:b][k, m0], D[a:b][k, mm]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(np.abs(D0 - D1) > 1e-9, (D0 - alvo) / (D0 - D1), 0.0)
        p = ns[m0] + np.clip(t, 0.0, 1.0) * (ns[mm] - ns[m0])
        p = _suavizar(p, SUAVE_DA_LINHA_MM / max(du, 1e-6))
        incl = np.degrees(np.arctan(np.abs(np.gradient(p, du))))
        fora[a:b] &= incl <= INCLINACAO_MAX_GRAUS
    return fora


def canais_possiveis(lo, hi, h, an, au, P):
    av = 3 - an - au
    larg_v = (hi[av] - lo[av]) * h
    util = larg_v - 2.0 * (P["raio_funil_mm"] + _compensacao(h, P["raio_mm"])
                           + PAREDE_MIN_MM)
    if util < 0:
        return 0, larg_v
    return int(math.floor(util / P["espacamento_mm"] + 1e-9)) + 1, larg_v


def tracar_canais(dist, J, lo, hi, h, an, sn, au, P, arvore=None,
                  validade=None):
    av = 3 - an - au
    r, r_f = P["raio_mm"], P["raio_funil_mm"]
    d, s = P["distancia_mm"], P["espacamento_mm"]
    alvo = d + 0.5 * h
    n, larg_v = canais_possiveis(lo, hi, h, an, au, P)
    if n < 1:
        raise B.Recusa(
            u"Caixa estreita demais para um canal: %s mm na direção entre os "
            u"canais, e um canal com parede pede %s mm. Alargue a caixa."
            % (_mm(larg_v), _mm(2.0 * (r_f + PAREDE_MIN_MM))))
    vs = [lo[av] * h + larg_v / 2.0 + (k - (n - 1) / 2.0) * s
          for k in range(n)]
    u0, u1 = lo[au] * h, hi[au] * h
    nu = int(math.ceil((u1 - u0) / PASSO_DO_PERFIL_MM)) + 1
    us_caixa = np.linspace(u0, u1, nu)
    du = (u1 - u0) / max(1, nu - 1)
    teto_u = (dist.shape[2 - au] - 1) * h
    folga_u = 2.0 * SUAVE_DA_LINHA_MM
    ne = int(math.floor(max(0.0, min(folga_u, u0)) / du))
    nd = int(math.floor(max(0.0, min(folga_u, teto_u - u1)) / du))
    us = np.concatenate([u0 - du * np.arange(ne, 0, -1), us_caixa,
                         u1 + du * np.arange(1, nd + 1)])
    i0, i1 = ne, ne + nu
    q0, q1 = trecho_exigido(i0, i1, u0, u1, du, P)
    n0, n1 = lo[an] * h, hi[an] * h
    passo_n = min(PASSO_DO_PERFIL_MM, h / 2.0)
    nn = int(math.ceil((n1 - n0) / passo_n)) + 1
    ns = np.linspace(n0, n1, nn)
    if sn > 0:
        ns = ns[::-1]
    canais, descartados = [], []
    for k, v in enumerate(vs):
        U, N = np.meshgrid(us, ns, indexing="ij")
        pts = np.empty(U.shape + (3,))
        pts[..., au], pts[..., an], pts[..., av] = U, N, v
        D = _amostrar(dist, pts.reshape(-1, 3), h).reshape(U.shape)
        Jv = _amostrar(J, pts.reshape(-1, 3), h).reshape(U.shape)
        del pts, U, N
        abaixo = D <= alvo
        tem = abaixo.any(axis=1)
        m = np.argmax(abaixo, axis=1)
        bloq = np.maximum.accumulate(Jv >= 0, axis=1)
        linhas = np.arange(len(us))
        bloq_m = bloq[linhas, m]
        valido = tem & (m > 0) & ~bloq_m
        if validade is not None:
            validade.append(_sem_ingreme(valido, D, m, ns, alvo, du)[i0:i1])
        if not valido[q0:q1].all():
            descartados.append(_descarte_do_trajeto(
                k, v, tem[q0:q1], m[q0:q1], bloq_m[q0:q1], du, au, alvo))
            continue
        a, b = q0, q1 - 1
        while a > 0 and valido[a - 1]:
            a -= 1
        while b < len(us) - 1 and valido[b + 1]:
            b += 1
        sel = slice(a, b + 1)
        m, m0 = m[sel], np.maximum(m[sel] - 1, 0)
        linhas = np.arange(b + 1 - a)
        D0, D1 = D[sel][linhas, m0], D[sel][linhas, m]
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(np.abs(D0 - D1) > 1e-9, (D0 - alvo) / (D0 - D1), 0.0)
        t = np.clip(t, 0.0, 1.0)
        perfil = ns[m0] + t * (ns[m] - ns[m0])
        if arvore is not None:
            perfil, achou = _refinar_na_pele(perfil, us[sel], v, au, an, av,
                                             sn, h, arvore, d)
            falha = ~achou[q0 - a:q1 - a]
            if (falha.mean() > FALHA_DO_REFINO_MAX
                    or _maior_sequencia(falha) * du > FALHA_DO_REFINO_MAX_MM):
                nao = int(falha.sum()) * du
                descartados.append({
                    "k": int(k), "v_mm": float(v), "causa": "refino",
                    "invalido_mm": float(nao),
                    "motivo": u"a pele medida não confirmou a distância em "
                              u"%d mm do trajeto" % max(1, _mm_para_fora(nao))})
                continue
            if not achou.all():
                ok = np.nonzero(achou)[0]
                perfil = np.interp(np.arange(len(perfil)), ok, perfil[ok])
        perfil = _suavizar(perfil, SUAVE_DA_LINHA_MM / max(du, 1e-6))
        antes, depois = max(0, a - i0), max(0, i1 - 1 - b)
        if antes or depois:
            # GUARDA: alem do fundo cego nao ha canal; a linha so precisa cobrir a caixa.
            perfil = np.concatenate([np.full(antes, perfil[0]), perfil,
                                     np.full(depois, perfil[-1])])
        base = min(a, i0)
        perfil = perfil[i0 - base:i1 - base]
        incl = np.degrees(np.arctan(np.abs(np.gradient(perfil, du))))[
            q0 - i0:q1 - i0]
        if float(incl.max()) > INCLINACAO_MAX_GRAUS:
            descartados.append({
                "k": int(k), "v_mm": float(v), "causa": "inclinacao",
                "invalido_mm": 0.0, "graus": float(incl.max()),
                "motivo": u"o canal desceria quase na vertical (%.0f°; o "
                          u"limite é %.0f°)" % (float(incl.max()),
                                                 INCLINACAO_MAX_GRAUS)})
            continue
        linha = np.empty((nu, 3))
        linha[:, au], linha[:, an], linha[:, av] = us_caixa, perfil, v
        canais.append({"k": int(k), "v_mm": float(v), "linha": linha})
    return canais, descartados, av


def _montar_canal(c, P, au, u0, u1, h):
    linha = c["linha"]
    r = P["raio_mm"]
    comp = _compensacao(h, r)
    cego = P["trajeto"] == "cego"
    entrada_inicio = P["entrada"] == "inicio"
    if cego:
        if entrada_inicio:
            pare = u1 - (r + FUNDO_CEGO_PAREDE_MM)
            dentro = linha[linha[:, au] <= pare]
        else:
            pare = u0 + (r + FUNDO_CEGO_PAREDE_MM)
            dentro = linha[linha[:, au] >= pare]
    else:
        dentro = linha
    if not entrada_inicio:
        dentro = dentro[::-1]
    ext = P["raio_funil_mm"] + 1.0 + 2.0 * h
    passo = PASSO_DO_PERFIL_MM
    t_ini = dentro[0] - dentro[min(4, len(dentro) - 1)]
    t_ini /= max(np.linalg.norm(t_ini), 1e-12)
    pre = dentro[0][None, :] + t_ini[None, :] * (
        np.arange(int(math.ceil(ext / passo)), 0, -1)[:, None] * passo)
    partes = [pre, dentro]
    if not cego:
        t_fim = dentro[-1] - dentro[max(0, len(dentro) - 5)]
        t_fim /= max(np.linalg.norm(t_fim), 1e-12)
        pos = dentro[-1][None, :] + t_fim[None, :] * (
            np.arange(1, int(math.ceil(ext / passo)) + 1)[:, None] * passo)
        partes.append(pos)
    toda = np.concatenate(partes)
    u = toda[:, au]
    faces_abertas = [u0, u1] if not cego else [u0 if entrada_inicio else u1]
    a_face = np.min([np.abs(u - f) for f in faces_abertas], axis=0)
    fora_da_caixa = (u < u0) | (u > u1)
    funil = np.zeros(len(toda))
    if P["funil"]:
        funil = FUNIL_MM * np.clip(1.0 - a_face / FUNIL_COMPRIMENTO_MM, 0.0,
                                   1.0)
        funil[fora_da_caixa] = FUNIL_MM
    raio = r + comp + funil
    c.update({"toda": toda, "raio_corte": raio,
              "na_caixa": ~fora_da_caixa, "dentro": dentro,
              "faces_abertas": faces_abertas, "pare": pare if cego else None})
    return c


def _medir_curvas(canais, P):
    for c in canais:
        R, s, q = raios_de_curvatura(c["dentro"])
        c["R"], c["s"], c["q"] = R, s, q
        fin = np.isfinite(R)
        c["raio_min_mm"] = float(R.min()) if fin.any() else float("inf")
        c["raio_min_em_mm"] = float(s[int(np.argmin(R))]) if fin.any() else None
        c["comprimento_mm"] = float(s[-1]) if len(s) else 0.0
        c["trechos_amarelos"] = trechos_abaixo(R, s,
                                               limiar_amarelo(P["padrao_mm"]))
    return min([c["raio_min_mm"] for c in canais] or [float("inf")])


def _menor_folga_entre_canais(canais):
    from scipy.spatial import cKDTree
    pior = float("inf")
    for i in range(len(canais)):
        a = canais[i]
        sa = a["na_caixa"]
        arv = cKDTree(a["toda"][sa])
        ra = a["raio_corte"][sa]
        for j in range(i + 1, len(canais)):
            b = canais[j]
            sb = b["na_caixa"]
            d, idx = arv.query(b["toda"][sb])
            folga = d - b["raio_corte"][sb] - ra[idx]
            pior = min(pior, float(folga.min()))
    return pior


def _paredes(canais, dist, lo, hi, h, an, av, P, arvore=None):
    T = P["corpo_mm"]
    pele_min, pele_max, parede = float("inf"), -float("inf"), float("inf")
    for c in canais:
        sel = c["na_caixa"]
        pts = c["toda"][sel]
        rc = c["raio_corte"][sel]
        if arvore is not None:
            dpele = arvore.query(pts)[0]
        else:
            dpele = _amostrar(dist, pts, h) - 0.5 * h
        caixa = np.min(np.stack([pts[:, av] - lo[av] * h, hi[av] * h - pts[:, av],
                                 pts[:, an] - lo[an] * h,
                                 hi[an] * h - pts[:, an]]), axis=0)
        p = np.minimum(np.minimum(dpele - rc, T - dpele - rc), caixa - rc)
        c["pele_min_mm"] = float(dpele.min())
        c["pele_max_mm"] = float(dpele.max())
        c["parede_min_mm"] = float(p.min())
        pele_min = min(pele_min, c["pele_min_mm"])
        pele_max = max(pele_max, c["pele_max_mm"])
        parede = min(parede, c["parede_min_mm"])
    return pele_min, pele_max, parede


def _cavar(F, canais, h):
    from scipy.spatial import cKDTree
    forma = np.array(F.shape[::-1])
    for c in canais:
        pts = c["toda"] / h
        rr = c["raio_corte"] / h
        alcance = float(rr.max()) + 2.0
        a = np.maximum(np.floor(pts.min(0) - alcance).astype(int), 0)
        b = np.minimum(np.ceil(pts.max(0) + alcance).astype(int) + 1, forma)
        if np.any(b <= a):
            continue
        zz, yy, xx = np.meshgrid(np.arange(a[2], b[2]), np.arange(a[1], b[1]),
                                 np.arange(a[0], b[0]), indexing="ij")
        q = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1).astype(
            np.float64)
        del zz, yy, xx
        arv = cKDTree(pts)
        k = int(min(4, len(pts)))
        dd, ii = arv.query(q, k=k, distance_upper_bound=alcance)
        dd = np.asarray(dd).reshape(len(q), k)
        ii = np.asarray(ii).reshape(len(q), k)
        ok = np.isfinite(dd)
        ii = np.where(ok, ii, 0)
        C = np.where(ok, (dd - rr[ii]) * h, np.inf).min(axis=1)
        sub = F[a[2]:b[2], a[1]:b[1], a[0]:b[0]]
        np.maximum(sub, (-C).reshape(sub.shape).astype(np.float32), out=sub)
    return F


def _medir_na_malha(canais, verts, faces, h, P, au):
    from scipy.spatial import cKDTree
    tri = np.asarray(verts, dtype=np.float32)[np.asarray(faces, np.int64)]
    arv = cKDTree(tri.mean(axis=1), leafsize=32)
    r_f = P["raio_funil_mm"]
    for c in canais:
        d = c["dentro"]
        u = d[:, au]
        longe = np.ones(len(d), dtype=bool)
        for f in c["faces_abertas"]:
            longe &= np.abs(u - f) > r_f + FUNIL_COMPRIMENTO_MM + 1.0
        if c["pare"] is not None:
            longe &= np.abs(u - c["pare"]) > P["raio_mm"] + 1.0
        idx = np.nonzero(longe)[0]
        if idx.size > MEDIDAS_POR_CANAL:
            idx = idx[np.linspace(0, idx.size - 1,
                                  MEDIDAS_POR_CANAL).astype(int)]
        if idx.size:
            m = B._distancia_exata(d[idx] / h, tri, arv) * h
            c["diametro_medido_mm"] = float(2.0 * m.min())
            c["diametro_mediano_mm"] = float(2.0 * np.median(m))
        else:
            c["diametro_medido_mm"] = None
            c["diametro_mediano_mm"] = None
        bocas = []
        for f in c["faces_abertas"]:
            j = int(np.argmin(np.abs(np.abs(u - f) - 1.0)))
            bocas.append(float(2.0 * B._distancia_exata(
                d[j:j + 1] / h, tri, arv)[0] * h))
        c["boca_medida_mm"] = bocas
    return canais


def _aberto(F, canais, h, P, au):
    from scipy import ndimage
    obstruido, fundo_aberto = 0, 0
    for c in canais:
        d = c["dentro"]
        p = d / h + 1.0
        v = ndimage.map_coordinates(F, [p[:, 2], p[:, 1], p[:, 0]], order=1,
                                    mode="nearest")
        obstruido += int((v <= 0).sum())
        if c["pare"] is not None:
            longe = d[-1].copy()
            sinal = 1.0 if P["entrada"] == "inicio" else -1.0
            longe[au] = c["pare"] + sinal * (P["raio_mm"]
                                            + FUNDO_CEGO_PAREDE_MM / 2.0)
            q = longe / h + 1.0
            w = ndimage.map_coordinates(F, [[q[2]], [q[1]], [q[0]]], order=1,
                                        mode="nearest")
            fundo_aberto += int(w[0] >= 0)
    return obstruido, fundo_aberto


def _campos(serie, cx, P, colocacao=None):
    from scipy.spatial import cKDTree
    T = P["corpo_mm"]
    h, off, forma = B._grade(serie, cx,
                             max(T + 2.0, 2.0 * SUAVE_DA_LINHA_MM + 1.0))
    J, corpo, lo, hi, direcao, dir_auto, av_mesa = B.campos_da_pele(
        serie, cx, h, off, forma, P["direcao"])
    if colocacao and direcao != colocacao:
        raise ColocacaoVirou(direcao)
    eixos = eixos_do_canal(P["eixo"], direcao)
    pele = pontos_da_pele(J, corpo, h, serie, off)
    if not len(pele):
        raise B.Recusa(u"Não achei pele na caixa: ela não encosta no corpo "
                       u"na direção de colocação.")
    arvore = cKDTree(pele, leafsize=32)
    del pele
    dist = B._distancia_fora(corpo, h)
    del corpo
    E = B._sdf_caixa(forma, lo, hi)
    E *= np.float32(h)
    F = dist - np.float32(T + 0.5 * h)
    np.maximum(F, E, out=F)
    del E
    np.maximum(F, J, out=F)
    if not (F < 0).any():
        raise B.Recusa(u"Não sobrou corpo: a caixa não encosta na pele na "
                       u"direção de colocação, ou tudo nela é sólido.")
    return {"h": h, "off": off, "forma": forma, "lo": lo, "hi": hi,
            "direcao": direcao, "dir_auto": dir_auto, "avisos_mesa": av_mesa,
            "eixos": eixos, "J": J, "dist": dist, "arvore": arvore, "F": F}


def comprimento_exigido(u0, u1, P):
    if P["trajeto"] == "cego":
        return u1 - u0 - (P["raio_mm"] + FUNDO_CEGO_PAREDE_MM)
    return u1 - u0


def _tracar_eixos(ctx, P):
    an, sn = B._NORMAL[ctx["direcao"]]
    h = ctx["h"]
    alvo = P["distancia_mm"] + 0.5 * h
    fora = []
    for au in ctx["eixos"]:
        maximo = canais_possiveis(ctx["lo"], ctx["hi"], h, an, au, P)[0]
        comp = comprimento_exigido(ctx["lo"][au] * h, ctx["hi"][au] * h, P)
        if (fora and maximo and fora[0]["uteis"] >= maximo
                and fora[0].get("seguro")):
            fora.append({"au": au, "av": 3 - an - au, "canais": [],
                         "descartados": [], "tentados": 0, "buraco": None,
                         "estreita": None, "validade": [], "comprimento": comp,
                         "uteis": 0, "maximo": maximo, "pulado": True,
                         "seguro": False})
            continue
        validade, estreita = [], None
        try:
            canais, descartados, av = tracar_canais(
                ctx["dist"], ctx["J"], ctx["lo"], ctx["hi"], h, an, sn, au, P,
                ctx["arvore"], validade)
        except B.Recusa as e:
            if len(ctx["eixos"]) < 2:
                raise
            canais, descartados, av, estreita = [], [], 3 - an - au, e
        tentados = len(canais) + len(descartados)
        buraco = recusa_canal_no_meio(canais, descartados, tentados,
                                      ctx["direcao"], au, av, alvo,
                                      comp) if canais else None
        seguro = bool(canais and buraco is None and estreita is None)
        if seguro:
            for c in canais:
                _montar_canal(c, P, au, ctx["lo"][au] * h,
                              ctx["hi"][au] * h, h)
            raio = _medir_curvas(canais, P)
            folga = (_menor_folga_entre_canais(canais)
                     if len(canais) > 1 else None)
            parede = _paredes(canais, ctx["dist"], ctx["lo"], ctx["hi"], h,
                              an, av, P, ctx["arvore"])[2]
            seguro = (raio >= P["piso_mm"]
                      and (folga is None or folga >= PAREDE_MIN_MM)
                      and parede >= PAREDE_MIN_MM / 2.0)
        fora.append({"au": au, "av": av, "canais": canais,
                     "descartados": descartados, "tentados": tentados,
                     "buraco": buraco, "estreita": estreita,
                     "validade": validade, "comprimento": comp,
                     "uteis": (len(canais) if buraco is None
                               and estreita is None else 0),
                     "maximo": maximo, "pulado": False, "seguro": seguro})
    return fora


def escolher_eixo(tracados):
    if all(t["estreita"] is not None for t in tracados):
        raise tracados[0]["estreita"]
    return max(tracados, key=lambda t: (bool(t.get("seguro")), t["uteis"],
                                       t is tracados[0]))


def _o_que_coube(t):
    if t.get("pulado"):
        return u"caberiam no máximo %d" % t["maximo"]
    if t["uteis"] and not t.get("seguro", True):
        return u"os canais não passaram nas conferências de segurança"
    if t["uteis"]:
        return u"couberam %d" % t["uteis"]
    return u"nenhum canal útil"


def frase_do_eixo_escolhido(escolha, tracados):
    outros = u"; ".join(
        u"na %s, %s" % (nome_do_eixo(t["au"]), _o_que_coube(t))
        for t in tracados if t is not escolha)
    return (u"Direção dos canais escolhida pelo app: %s, com %d %s; %s." % (
        nome_do_eixo(escolha["au"]), escolha["uteis"],
        u"canal" if escolha["uteis"] == 1 else u"canais", outros))


def _maior_trecho(w):
    w = np.concatenate([[False], np.asarray(w, dtype=bool), [False]])
    d = np.diff(w.astype(np.int8))
    ini, fim = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    if not ini.size:
        return 0, 0
    j = int(np.argmax(fim - ini))
    return int(ini[j]), int(fim[j])


def intervalo_com_canais(validade, du, minimo_mm):
    V = np.asarray(validade, dtype=bool)
    if V.ndim != 2 or not V.size:
        return None
    n = V.shape[0]
    melhor = None
    for k0 in range(n):
        W = np.ones(V.shape[1], dtype=bool)
        for k1 in range(k0, n):
            W &= V[k1]
            a, b = _maior_trecho(W)
            comp = (b - 1 - a) * du
            if b <= a or comp < minimo_mm:
                break
            ks = np.nonzero(V[:, a:b].all(axis=1))[0]
            # GUARDA: canal caido entre canais aceitos e o buraco que a geracao recusa.
            if not ks.size or ks[-1] - ks[0] + 1 != ks.size:
                continue
            nota = (ks.size * comp, comp)
            if melhor is None or nota > melhor[0]:
                melhor = (nota, a, b, int(ks.size))
    return melhor


def caixa_sugerida(serie, cx, P, ctx, tracados):
    h, off, lo, hi = ctx["h"], ctx["off"], ctx["lo"], ctx["hi"]
    margem = MARGEM_DA_SUGERIDA_MM
    melhor = None
    for t in tracados:
        if t["estreita"] is not None or not t["validade"]:
            continue
        au = t["au"]
        u0, u1 = lo[au] * h, hi[au] * h
        nu = len(t["validade"][0])
        du = (u1 - u0) / max(1, nu - 1)
        iv = intervalo_com_canais(t["validade"], du,
                                  B.CAIXA_MIN_MM + 2.0 * margem)
        if iv is None:
            continue
        nota, a, b, _n = iv
        ua = u0 + a * du + (margem if a > 0 else 0.0)
        ub = u0 + (b - 1) * du - (margem if b < nu else 0.0)
        if ub - ua < B.CAIXA_MIN_MM or ub - ua >= u1 - u0 - 1e-6:
            continue
        if melhor is None or nota > melhor[0]:
            melhor = (nota, au, ua, ub, u1 - u0)
    if melhor is None:
        return None
    _nota, au, ua, ub, desenhada = melhor
    eixo = "xyz"[au]
    cx2 = dict(cx)
    cx2[eixo + "0"] = float(off[au] + ua)
    cx2[eixo + "1"] = float(off[au] + ub)
    # GUARDA: confere so o eixo aparado; com o eixo automatico, a geracao fica com o que der mais.
    P2 = dict(P, eixo=dict((e[1], e[0]) for e in EIXOS)[au])
    try:
        tr2 = _tracar_eixos(_campos(serie, cx2, P2, ctx["direcao"]), P2)
    except ColocacaoVirou as v:
        # GUARDA: a sugestao promete a colocacao desta geracao; com outra, seria outro aplicador.
        return {"descartada": True, "caixa": cx2, "mm": float(ub - ua),
                "mm_desenhada": float(desenhada), "eixo_canal": int(au),
                "colocacao": ctx["direcao"],
                "colocacao_na_sugerida": v.direcao}
    except B.Recusa:
        return None
    if tr2[0]["uteis"] < 1:
        return None
    return {"caixa": cx2, "mm": float(ub - ua), "mm_desenhada": float(desenhada),
            "canais": int(tr2[0]["uteis"]), "eixo_canal": int(au)}


def _recusa_sem_uteis(serie, cx, P, ctx, tracados):
    rel = tracados[0] if tracados[0]["estreita"] is None else next(
        t for t in tracados if t["estreita"] is None)
    e = rel["buraco"] or recusa_sem_canal(
        rel["descartados"], rel["tentados"], ctx["direcao"], ctx["dir_auto"],
        rel["au"], rel["av"], P["distancia_mm"] + 0.5 * ctx["h"],
        rel["comprimento"])
    for k in ("J", "dist", "arvore", "F"):
        ctx.pop(k, None)
    return com_sugerida(e, [t["au"] for t in tracados if t is not rel],
                        caixa_sugerida(serie, cx, P, ctx, tracados))


def gerar(serie, caixa, parametros=None):
    t0 = time.time()
    P = conferir_parametros(parametros)
    cx = B.normalizar_caixa(serie, caixa)
    T = P["corpo_mm"]
    ctx = _campos(serie, cx, P)
    h, off, forma, lo, hi = (ctx["h"], ctx["off"], ctx["forma"], ctx["lo"],
                             ctx["hi"])
    direcao, dir_auto = ctx["direcao"], ctx["dir_auto"]
    an, sn = B._NORMAL[direcao]
    avisos = list(ctx["avisos_mesa"]) + list(P["alertas"])
    tracados = _tracar_eixos(ctx, P)
    escolha = escolher_eixo(tracados)
    if not escolha["uteis"]:
        raise _recusa_sem_uteis(serie, cx, P, ctx, tracados)
    dist, arvore, F = ctx.pop("dist"), ctx.pop("arvore"), ctx.pop("F")
    del ctx["J"]
    au, av = escolha["au"], escolha["av"]
    canais, descartados = escolha["canais"], escolha["descartados"]
    tentados = escolha["tentados"]
    face_entrada = face_de_entrada(au, P["entrada"])
    if len(tracados) > 1:
        avisos.append(frase_do_eixo_escolhido(escolha, tracados))
    u0, u1 = lo[au] * h, hi[au] * h
    for c in canais:
        _montar_canal(c, P, au, u0, u1, h)
    for i, c in enumerate(canais):
        c["n"] = i + 1

    raio_min = _medir_curvas(canais, P)
    if raio_min < P["piso_mm"]:
        pior = min(canais, key=lambda c: c["raio_min_mm"])
        resumo = (
            u"Curva abaixo do piso: o canal %d tem raio mínimo de %s mm (a %s "
            u"mm da face %s, a de entrada), e o piso de %s com %s é %s mm. O "
            u"aplicador não é gerado: um canal assim pode prender o cateter "
            u"ou a fonte."
            % (pior["n"], _mm(pior["raio_min_mm"]),
               _mm(pior["raio_min_em_mm"], 0), face_entrada,
               P["afterloader_nome"],
               P["cateter_nome"], _mm(P["piso_mm"], 0)))
        raise Bloqueio(
            resumo + u" Proponho: " + u" ".join(PROPOSTAS),
            {"motivo": "raio_abaixo_do_piso", "canal": pior["n"],
             "resumo": resumo,
             "raio_min_mm": pior["raio_min_mm"], "piso_mm": P["piso_mm"],
             "propostas": list(PROPOSTAS)}, "raio")

    folga = _menor_folga_entre_canais(canais) if len(canais) > 1 else None
    if folga is not None and folga < PAREDE_MIN_MM:
        raise Bloqueio(
            u"Canais que se cruzam: a parede entre dois canais chegaria a %s "
            u"mm, e o mínimo é %s mm. Aumente o espaçamento."
            % (_mm(folga), _mm(PAREDE_MIN_MM)),
            {"motivo": "canais_cruzam", "parede_mm": folga}, "espacamento_mm")

    pele_min, pele_max, parede = _paredes(canais, dist, lo, hi, h, an, av, P,
                                          arvore)
    del arvore
    if parede < PAREDE_MIN_MM / 2.0:
        raise Bloqueio(
            u"O canal romperia a parede da peça: sobram %s mm em algum ponto "
            u"(a distância à pele foi de %s a %s mm, e o corpo tem %s mm). "
            u"Afaste o canal da pele, engrosse o corpo, ou alargue a caixa."
            % (_mm(parede), _mm(pele_min), _mm(pele_max), _mm(T)),
            {"motivo": "parede", "parede_mm": parede}, "distancia_mm")
    if parede < PAREDE_MIN_MM:
        avisos.append(u"Parede fina: sobram %s mm entre o canal e a face da "
                      u"peça em algum ponto (mínimo recomendado: %s mm). "
                      u"Confira a impressão." % (_mm(parede),
                                                  _mm(PAREDE_MIN_MM)))
    d = P["distancia_mm"]
    if (d - pele_min > DESVIO_DA_PELE_AVISO_MM
            or pele_max - d > DESVIO_DA_PELE_AVISO_MM):
        avisos.append(u"A distância medida do eixo do canal à pele foi de %s "
                      u"a %s mm (pedida: %s mm): a linha do canal é "
                      u"suavizada onde a pele faz curva." % (
                          _mm(pele_min), _mm(pele_max), _mm(d)))
    for x in descartados:
        avisos.append(u"Um canal não coube e ficou fora (o %dº dos %d "
                      u"tentados, contados do lado %s): %s."
                      % (x.get("k", 0) + 1, tentados, LADOS[int(av)][0],
                         x["motivo"]))
    del dist

    F = _cavar(F, canais, h)
    Fp = np.pad(F, 1, mode="constant", constant_values=1.0)
    del F
    r_rente = np.float32(B.RENTE_POR_GRADE * h)
    rente = np.abs(Fp) < r_rente
    Fp[rente] = r_rente
    del rente
    F = Fp[1:-1, 1:-1, 1:-1]
    mask = F < 0
    verts, faces = B.superficie(Fp)
    verts = verts - 1.0
    obstruido, fundo_aberto = _aberto(Fp, canais, h, P, au)
    if obstruido or fundo_aberto:
        raise Bloqueio(
            u"Conferência da malha: %s. O aplicador não é gerado." % (
                u"um canal saiu obstruído" if obstruido
                else u"o fundo cego saiu aberto"),
            {"motivo": "canal_obstruido" if obstruido else "fundo_aberto"})
    _medir_na_malha(canais, verts, faces, h, P, au)
    medidos = [c["diametro_medido_mm"] for c in canais
               if c["diametro_medido_mm"] is not None]
    od = P["diametro_externo_mm"]
    if medidos and min(medidos) < od:
        raise Bloqueio(
            u"O canal impresso ficaria mais estreito que o cateter: %s mm "
            u"medidos na malha, contra %s mm do cateter. Alargue o canal."
            % (_mm(min(medidos), 2), _mm(od)),
            {"motivo": "canal_estreito", "medido_mm": min(medidos)},
            "canal_mm")
    if medidos and min(medidos) - od < FOLGA_SEM_ALERTA_MM and \
            P["folga_mm"] >= FOLGA_SEM_ALERTA_MM:
        avisos.append(u"A folga medida na malha ficou em %s mm, abaixo de %s "
                      u"mm: imprima uma peça de calibração antes."
                      % (_mm(min(medidos) - od, 2), _mm(FOLGA_SEM_ALERTA_MM)))

    lps = serie.quadro_para_lps(off[None, :] + verts * h)
    faces_lps = faces[:, [0, 2, 1]] if np.linalg.det(serie.D) < 0 else faces
    malha = B.conferir_malha(lps, faces_lps)
    stl = B.stl_binario(lps, faces_lps, cabecalho=CABECALHO_STL)
    del lps, faces_lps

    def _para_indice(t):
        q = serie.lps_para_quadro(t.reshape(-1, 3)).reshape(-1, 3, 3)
        q -= off[None, None, :]
        q /= h
        return q

    volta, impares = B.voxelizar(B._triangulos_do_stl(stl), mask.shape,
                                 para_indice=_para_indice)
    dsc_volta = B.dsc(volta, mask)
    del volta
    from scipy import ndimage
    rot, n_pecas = ndimage.label(mask, structure=np.ones((3, 3, 3)))
    del rot
    ext_q = off[None, :] + verts * h
    dims = (ext_q.max(0) - ext_q.min(0)) if len(verts) else np.zeros(3)
    del ext_q, verts, faces
    previa = B._previa_do_bolus(mask, off, h, F)

    amarela = curva_e_amarela(raio_min, P["padrao_mm"])
    classe = "amarelo" if amarela else "verde"
    exigencias = list(EXIGENCIAS)
    if classe == "amarelo":
        pior = min(canais, key=lambda c: c["raio_min_mm"])
        avisos.insert(0, u"Curva amarela: raio mínimo de %s mm no canal %d (a "
                         u"%s mm da face %s, a de entrada), entre o piso de "
                         u"%s mm e o padrão de %s mm. Os trechos de cada "
                         u"canal e as exigências da curva estão na ficha."
                         % (_mm(raio_min), pior["n"],
                            _mm(pior["raio_min_em_mm"], 0), face_entrada,
                            _mm(P["piso_mm"], 0),
                            _mm(limiar_amarelo(P["padrao_mm"]), 0)))
        exigencias += list(EXIGENCIAS_DA_CURVA)
    face = B.parece_face(serie, cx)
    if face:
        avisos.append(AVISO_BIOMETRIA)
    exportavel = bool(malha["fechada"])
    if not exportavel:
        avisos.append(u"A malha não fechou: o STL não é exportado.")
    publicos = {k: v for k, v in P.items() if k != "alertas"}
    return {
        "peca": "aplicador", "parametros": publicos,
        "direcao": direcao, "direcao_automatica": dir_auto,
        "eixo_canal": int(au), "eixo_canal_nome": nome_do_eixo(au),
        "eixo_canal_automatico": len(tracados) > 1,
        "eixos_tracados": [{"eixo": int(t["au"]),
                            "nome": nome_do_eixo(t["au"]),
                            "canais": int(t["uteis"]),
                            "tracado": not t["pulado"]} for t in tracados],
        "face_entrada": face_entrada,
        "eixo_espacamento": int(av), "grade_mm": h, "caixa": cx,
        "off": off.tolist(), "forma": list(forma),
        "canais": [_canal_publico(c, au) for c in canais],
        "descartados": descartados, "raio_min_mm": float(raio_min),
        "classe": classe, "piso_mm": P["piso_mm"],
        "padrao_mm": P["padrao_mm"], "pele_min_mm": pele_min,
        "pele_max_mm": pele_max, "parede_min_mm": parede,
        "folga_entre_canais_mm": folga,
        "malha": malha, "dsc_ida_volta": float(dsc_volta),
        "colunas_impares": int(impares), "pecas": int(n_pecas),
        "volume_cm3": malha["volume_mm3"] / 1000.0,
        "dimensoes_mm": [float(v) for v in dims], "avisos": avisos,
        "exigencias": exigencias, "face": face, "exportavel": exportavel,
        "tempo_s": round(time.time() - t0, 2), "stl": stl, "mask": mask,
        "previa": previa, "molde": None,
        "linhas_centrais_quadro": [
            (off[None, :] + c["dentro"]).tolist() for c in canais],
    }


def _canal_publico(c, au):
    return {"n": c["n"], "v_mm": c["v_mm"],
            "comprimento_mm": c["comprimento_mm"],
            "raio_min_mm": c["raio_min_mm"],
            "raio_min_em_mm": c["raio_min_em_mm"],
            "trechos_amarelos": [list(t) for t in c["trechos_amarelos"]],
            "pele_min_mm": c["pele_min_mm"], "pele_max_mm": c["pele_max_mm"],
            "parede_min_mm": c["parede_min_mm"],
            "diametro_medido_mm": c.get("diametro_medido_mm"),
            "diametro_mediano_mm": c.get("diametro_mediano_mm"),
            "boca_medida_mm": c.get("boca_medida_mm") or []}


def _json(v):
    if isinstance(v, dict):
        return dict((k, _json(x)) for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return [_json(x) for x in v]
    if isinstance(v, (np.floating, float)):
        v = float(v)
        return v if math.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _face_do_resultado(res):
    return res.get("face_entrada") or face_de_entrada(
        res["eixo_canal"], res["parametros"]["entrada"])


def _padrao_txt(P):
    sugerido = P.get("padrao_sugerido_mm", RAIO_PADRAO_MM)
    if abs(float(P["padrao_mm"]) - float(sugerido)) < 1e-9:
        return u"%s mm" % _mm(P["padrao_mm"], 0)
    return u"%s mm (o sugerido é %s mm)" % (_mm(P["padrao_mm"]),
                                           _mm(sugerido, 0))


def linhas_de_parametros(res):
    P = res["parametros"]
    face = _face_do_resultado(res)
    if P["trajeto"] == "aberto":
        trajeto = u"aberto: ponta e conector saem do corpo"
    else:
        trajeto = u"fundo cego: só a face de entrada é aberta"
    return [
        (u"Afterloader", u"%s · piso %s mm" % (
            P["afterloader_nome"], _mm(P["afterloader_piso_mm"], 0))),
        (u"Cateter", u"%s · Ø externo %s mm · piso %s mm" % (
            P["cateter_nome"], _mm(P["diametro_externo_mm"]),
            _mm(P["cateter_piso_mm"], 0))),
        (u"Piso do raio (bloqueia)", u"%s mm, o maior dos dois"
         % _mm(P["piso_mm"], 0)),
        (u"Raio padrão (abaixo dele, curva amarela)", _padrao_txt(P)),
        (u"Canal", u"Ø %s mm · folga %s mm" % (_mm(P["canal_mm"]),
                                                _mm(P["folga_mm"]))),
        (u"Eixo do canal até a pele", u"%s mm" % _mm(P["distancia_mm"])),
        (u"Espaçamento entre canais", u"%s mm" % _mm(P["espacamento_mm"])),
        (u"Espessura do corpo", u"%s mm" % _mm(P["corpo_mm"])),
        (u"Trajeto", trajeto),
        (u"Face de entrada do cateter (as distâncias contam dela)", face),
        (u"Entrada afunilada", (u"sim: Ø +%s mm na boca, em %s mm"
                                % (_mm(2 * FUNIL_MM), _mm(FUNIL_COMPRIMENTO_MM,
                                                          0)))
         if P["funil"] else u"não"),
        (u"Direção de colocação", DIRECAO_POR_EXTENSO.get(res["direcao"],
                                                          res["direcao"])),
        (u"Direção dos canais", res["eixo_canal_nome"] + (
            u" (escolhida pelo app)" if res.get("eixo_canal_automatico")
            else u"")),
    ]


def trechos_para_fora(trechos, comprimento):
    fora = []
    for a, b in trechos:
        ini = max(0.0, math.floor(float(a)))
        fim = math.ceil(float(b))
        if comprimento is not None and math.isfinite(float(comprimento)):
            fim = min(fim, math.ceil(float(comprimento)))
        fora.append((ini, max(ini, fim)))
    return fora


def linhas_dos_canais(res):
    lado0, lado1 = LADOS[res["eixo_espacamento"]]
    face = _face_do_resultado(res)
    padrao = _mm(limiar_amarelo(res["padrao_mm"]), 0)
    fora = [u"Os canais são numerados do lado %s para o lado %s do "
            u"paciente. Todas as distâncias ao longo do canal contam da face "
            u"%s, a face de entrada do cateter, e são medidas na linha "
            u"central." % (lado0, lado1, face)]
    curvas = []
    for c in res["canais"]:
        raio = _raio_txt(c["raio_min_mm"])
        if raio[0].isdigit():
            raio = u"raio mínimo %s a %s mm da face %s" % (
                raio, _mm(c["raio_min_em_mm"], 0), face)
        fora.append(
            u"Canal %d: entra pela face %s · %s mm de comprimento · %s · eixo "
            u"a %s–%s mm da pele · Ø medido na malha %s mm" % (
                c["n"], face, _mm(c["comprimento_mm"], 0), raio,
                _mm(c["pele_min_mm"]), _mm(c["pele_max_mm"]),
                _mm(c["diametro_medido_mm"], 2)))
        tr = trechos_para_fora(c["trechos_amarelos"], c.get("comprimento_mm"))
        if tr:
            curvas.append(
                u"Canal %d, curva amarela (raio abaixo de %s mm): %s da face "
                u"%s. Nenhuma parada ativa nesses trechos." % (
                    c["n"], padrao, u"; ".join(
                        u"começa a %s mm e termina a %s mm" % (_mm(a, 0),
                                                               _mm(b, 0))
                        for a, b in tr), face))
        elif res.get("classe") == "amarelo":
            curvas.append(u"Canal %d: nenhum trecho abaixo de %s mm."
                          % (c["n"], padrao))
    if curvas:
        fora.append(u"Trechos de curva amarela, contados da face %s e "
                    u"arredondados para fora, ao milímetro:" % face)
        fora += curvas
    return fora


def nome_do_aplicador(res, sorteio):
    s = u"".join(ch for ch in str(sorteio or u"")
                 if ch in u"0123456789abcdef")[:8]
    P = res.get("parametros") or {}
    tipo = u"blind" if P.get("trajeto") == "cego" else u"open"
    return u"RadAI_applicator_DRAFT_%dch_d%dmm_%s_%s" % (
        len(res.get("canais") or []),
        int(round(float(P.get("distancia_mm") or 0))), tipo, s)


def ficha(res, nome_stl, quando=None):
    P = res["parametros"]
    quando = quando or time.strftime("%Y-%m-%d %H:%M")
    L = [u"RadAI · 3D Printed Bolus · APLICADOR DE SUPERFÍCIE PARA "
         u"BRAQUITERAPIA — FICHA",
         u"RASCUNHO NÃO APROVADO — sujeito a revisão física e médica.",
         u"",
         u"Arquivo STL: %s" % nome_stl,
         u"Gerado em: %s (milímetros, no sistema de coordenadas do paciente, "
         u"LPS)" % quando,
         u"Curva: %s · raio mínimo medido %s · piso %s mm · padrão %s mm"
         % (u"AMARELA" if res["classe"] == "amarelo" else u"verde",
            _raio_txt(res["raio_min_mm"]), _mm(res["piso_mm"], 0),
            _mm(res["padrao_mm"], 0)),
         u"",
         u"AVISOS QUE NÃO SOMEM"]
    L += [u"- %s" % e for e in res["exigencias"]]
    L += [u"", u"PARÂMETROS"]
    L += [u"- %s: %s" % (a, b) for a, b in linhas_de_parametros(res)]
    L += [u"- Fonte do piso do afterloader: %s" % P["afterloader_fonte"],
          u"- Fonte do piso do cateter: %s" % P["cateter_fonte"]]
    L += [u"", u"CANAIS (curvatura medida na linha central reamostrada a "
               u"cada %s mm; diâmetro medido de volta na malha)"
          % _mm(PASSO_DA_LINHA_MM)]
    L += [u"- %s" % x for x in linhas_dos_canais(res)]
    m = res["malha"]
    L += [u"", u"MALHA",
          u"- fechada: %s · ida e volta STL → voxel (DSC): %.4f · %d "
          u"triângulos · %d peça(s)" % (u"sim" if m["fechada"] else u"NÃO",
                                        res["dsc_ida_volta"],
                                        m["triangulos"], res["pecas"]),
          u"- volume do material: %s cm³ · dimensões: %s mm · grade de "
          u"trabalho: %s mm" % (_mm(res["volume_cm3"]),
                                u" × ".join(u"%d" % round(v)
                                            for v in res["dimensoes_mm"]),
                                _mm(res["grade_mm"], 2))]
    if res["avisos"]:
        L += [u"", u"ALERTAS"]
        L += [u"- %s" % a for a in res["avisos"]]
    L += [u"", u"MATERIAL", u"- " + MATERIAL, u"- " + MATERIAL_REFERENCIAS]
    L += [u"", u"REFERÊNCIAS (conferidas na origem)"]
    L += [u"- %s" % r for r in REFERENCIAS]
    L += [u"", u"CURVATURA"]
    L += [u"- %s" % r for r in PESQUISA_DE_CURVATURA]
    L += [u"", u"Este arquivo não leva nome, registro, data de exame nem "
               u"identificador de paciente."]
    return u"\r\n".join(L) + u"\r\n"


def pacote(res, sorteio, quando=None):
    raiz = nome_do_aplicador(res, sorteio)
    nome_stl = raiz + u".stl"
    nome_ficha = raiz + u"_FICHA.txt"
    texto = ficha(res, nome_stl, quando)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome_stl, res["stl"])
        z.writestr(nome_ficha, b"\xef\xbb\xbf" + texto.encode("utf-8"))
    return raiz + u".zip", buf.getvalue(), nome_stl


def conferir_ato(res, declaro, frase, declaro_curva=None, frase_curva=None):
    if declaro is not True:
        raise B.Recusa(u"Exportação recusada: falta o ato declarado. Marque a "
                       u"declaração — ela vale para uma exportação só.")
    if u" ".join(str(frase or u"").split()) != u" ".join(FRASE_DO_ATO.split()):
        raise B.Recusa(u"Exportação recusada: a frase declarada não é a do "
                       u"ato.")
    if res is not None and (res.get("classe") == "amarelo" or curva_e_amarela(
            res.get("raio_min_mm"), res.get("padrao_mm", RAIO_PADRAO_MM))):
        if declaro_curva is not True or u" ".join(
                str(frase_curva or u"").split()) != u" ".join(
                    FRASE_DA_CURVA.split()):
            raise B.Recusa(u"Exportação recusada: a curva é amarela, e falta "
                           u"a declaração das exigências da curva.")
    return True


def linha_do_ato(res, nome_stl):
    P = res["parametros"]
    return (u"[bolus] STL do APLICADOR exportado por ato declarado: %s | %d "
            u"canais | canal %s mm a %s mm da pele, %s mm entre canais | "
            u"corpo %s mm | %s | %s | piso %s mm | padrao %s mm | entrada "
            u"pela face %s | raio minimo medido %s | curva %s | %d "
            u"triangulos" % (
                nome_stl, len(res["canais"]), _mm(P["canal_mm"]),
                _mm(P["distancia_mm"]), _mm(P["espacamento_mm"]),
                _mm(P["corpo_mm"]), P["afterloader_nome"], P["cateter_nome"],
                _mm(P["piso_mm"], 0), _mm(P["padrao_mm"]),
                _face_do_resultado(res), _raio_txt(res["raio_min_mm"]),
                res["classe"], int(res["malha"]["triangulos"])))


def resumo(res):
    fora = {}
    for k, v in res.items():
        if k in ("stl", "mask", "previa", "linhas_centrais_quadro"):
            continue
        fora[k] = v
    pv = res.get("previa") or {}
    fora["previa"] = {"sp": pv.get("sp"), "off": pv.get("off"),
                      "forma": pv.get("forma")}
    fora["bytes_stl"] = len(res.get("stl") or b"")
    fora["parametros_tela"] = [list(x) for x in linhas_de_parametros(res)]
    fora["canais_tela"] = linhas_dos_canais(res)
    return _json(fora)
