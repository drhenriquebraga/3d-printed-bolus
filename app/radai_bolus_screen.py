# -*- coding: utf-8 -*-
import os
import threading
import time

import radai_bolus
import radai_menu
import radai_web


SOLTAR_APOS_S = 10 * 60
_S = {"b": None, "serie": None, "visto": 0.0, "relogio": None,
      "res": None, "r": None}
_TRAVA = threading.Lock()
_TRAVA_GERAR = threading.Lock()
_L = {}


def _esquecer():
    _S.update({"b": None, "serie": None, "res": None, "r": None})


def _armar(segundos):
    if _S.get("relogio") is not None:
        return
    t = threading.Timer(max(1.0, float(segundos)), _soltar_se_parada)
    t.daemon = True
    _S["relogio"] = t
    t.start()


def _soltar_se_parada(agora=None, rearmar=True):
    agora = time.time() if agora is None else float(agora)
    with _TRAVA:
        _S["relogio"] = None
        if _S["serie"] is None:
            return None
        parada = agora - float(_S.get("visto") or 0.0)
        if parada >= SOLTAR_APOS_S:
            _esquecer()
            return None
        falta = SOLTAR_APOS_S - parada
        if rearmar:
            _armar(falta)
        return falta


def _serie(b):
    with _TRAVA:
        if _S["b"] == b and _S["serie"] is not None:
            _S["visto"] = time.time()
            return _S["serie"]
    return None


def _publicar(b, serie, res):
    with _TRAVA:
        if _S["b"] != b or _S["serie"] is not serie:
            raise radai_bolus.Recusa(
                u"A série mudou durante a geração: este bólus era da série "
                u"anterior e foi descartado. Gere de novo.")
        rid = radai_bolus.sorteio()
        _S["res"], _S["r"], _S["visto"] = res, rid, time.time()
    return rid


ARQUIVO_ATOS = "radai_bolus_atos.log"


def arquivo_de_atos():
    import radai_archive
    return os.path.join(str(radai_archive.raiz()), ARQUIVO_ATOS)


def _gravar_ato(linha):
    import io
    caminho = arquivo_de_atos()
    pasta = os.path.dirname(caminho)
    if pasta:
        os.makedirs(pasta, exist_ok=True)
    with io.open(caminho, "a", encoding="utf-8", newline="\n") as f:
        f.write(u"[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), linha))
        f.flush()
        os.fsync(f.fileno())
    return caminho


def rotulo_de(s):
    esp = s.get("espessura_mm")
    num = s.get("numero")
    if isinstance(num, float) and num.is_integer():
        num = int(num)
    return (u"%s · série %s · %d cortes · %s · %s · …%s"
            % (s.get("modalidade") or u"?",
               num if num is not None else u"?", int(s.get("cortes") or 0),
               (u"%.2f mm" % esp) if esp else u"esp. ?",
               s.get("date") or u"sem data",
               (s.get("uid") or u"")[-8:]))


def lista_para_a_tela(achadas, fazer_bilhete):
    fora = []
    for s in achadas:
        b = fazer_bilhete(s.get("zip") or s.get("pasta") or u"",
                          s.get("uid") or u"")
        recusa = u""
        try:
            radai_bolus.conferir_modalidade(s.get("modalidade"))
        except radai_bolus.Recusa as e:
            recusa = str(e)
        fora.append({"b": b, "rotulo": rotulo_de(s), "recusada": recusa})
    return fora


SERIE_FORA_DO_ACERVO = u"a série não está mais no acervo"
USO_DA_VARREDURA = "bolus"
MIN_CORTES = 20
CAMPOS_DA_LINHA = ("bilhete",)


def linha_do_bolus(linha, pasta, s):
    if int(s.get("cortes") or 0) < MIN_CORTES:
        return False
    b = linha.get("bilhete") or u""
    if not b:
        return False
    serie = {"pasta": pasta, "uid": str(s.get("uid") or u""),
             "modalidade": linha.get("modalidade") or u"",
             "cortes": int(s.get("cortes") or 0),
             "numero": s.get("numero"),
             "espessura_mm": s.get("espessura_mm"),
             "date": linha.get("date") or u""}
    f = lista_para_a_tela([serie], lambda _p, _u: b)[0]
    _L[b] = serie
    for k in list(linha):
        if k not in CAMPOS_DA_LINHA:
            linha.pop(k, None)
    linha.update(f)
    return True


def registrar_varredura():
    import radai_varrer
    return radai_varrer.registrar_series_de_pasta(
        USO_DA_VARREDURA, enriquecer=linha_do_bolus)


def serie_do_acervo(bilhete, resolver=None, detalhes=None):
    import radai_tabela_acervo
    resolver = resolver or radai_tabela_acervo.resolver
    detalhes = detalhes or radai_tabela_acervo.detalhes
    pasta, uid = resolver(bilhete)
    if not pasta:
        return {"erro": SERIE_FORA_DO_ACERVO}
    d = (list(detalhes([bilhete]) or []) or [{}])[0] or {}
    s = {"pasta": pasta, "uid": uid or u"",
         "modalidade": d.get("modalidade") or u"",
         "cortes": int(d.get("cortes") or 0),
         "espessura_mm": d.get("espessura_mm")}
    f = lista_para_a_tela([s], lambda _p, _u: bilhete)[0]
    _L[f["b"]] = s
    return f


CSS = u"""
.bo-wrap{display:flex;flex-direction:column;gap:12px;padding:0 18px 28px;
 max-width:1440px;margin:0 auto;box-sizing:border-box}
.bo-pecas{display:flex;gap:8px;flex-wrap:nowrap}
.bo-pecas button{flex:1 1 auto;min-width:0;line-height:1.25}
.bo-pecas .bo-bt{flex:0 0 auto;white-space:nowrap}
.bo-bt2[disabled]{opacity:.45;cursor:default}
.bo-linha .ui-bt{height:36px}
.bo-alerta{border-left:4px solid var(--warn,#E1B23B);background:var(--panel-2);
 padding:10px 14px;border-radius:0 8px 8px 0;font-size:13.5px;line-height:1.6;
 color:var(--text)}
.bo-alerta b{color:var(--warn,#E1B23B)}
.bo-linha{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
.bo-campo{display:flex;flex-direction:column;gap:4px;min-width:200px;flex:1}
.bo-campo label,.bo-rot,.bo-mpr-rot{font-size:11px;letter-spacing:.08em;
 text-transform:uppercase;color:var(--text-muted)}
.bo-campo select,.bo-campo input,.bo-ctl select,.bo-ctl input[type=number]{
 background:var(--panel-2);color:var(--text);border:1px solid var(--line);
 border-radius:8px;padding:7px 9px;font:inherit;font-size:13px}
.bo-bt{background:var(--mod-bolus,#B5D65A);color:var(--mod-bolus-txt,#101a06);
 border:0;
 border-radius:9px;padding:9px 18px;font:inherit;font-weight:700;cursor:pointer}
.bo-bt[disabled]{opacity:.45;cursor:default}
.bo-bt2{background:transparent;color:var(--text);border:1px solid var(--line);
 border-radius:9px;padding:8px 14px;font:inherit;font-size:13px;cursor:pointer}
.bo-bt2.on{border-color:var(--mod-bolus,#B5D65A);color:var(--mod-bolus,#B5D65A)}
.bo-msg{font-size:13px;color:var(--text-muted);min-height:18px}
.bo-serie-l{display:flex;gap:8px;align-items:center}
.bo-campo-l{display:flex;gap:6px;align-items:stretch}
.bo-campo-l input{flex:1 1 auto;min-width:0}
.bo-filtro{margin:10px 0 0}
#bo-busca{margin:8px 0 0}
.bo-serie-l select{flex:1 1 auto;min-width:0}
.bo-msg.erro{color:var(--perigo)}
.bo-ctl[hidden],.bo-pecas[hidden],.bo-ctl .g[hidden],.bo-ato[hidden]{display:none}
.bo-peca-esc{display:flex;gap:16px;align-items:center;flex-wrap:wrap;
 font-size:13px;background:var(--panel);border:1px solid var(--line);
 border-radius:10px;padding:10px 14px}
.bo-peca-esc label{display:inline-flex;gap:6px;align-items:center;cursor:pointer}
.bo-ap-alerta{font-size:12.5px;padding:8px 12px}
.bo-ap-ck{display:inline-flex;gap:8px;align-items:center;font-size:13px;cursor:pointer}
.bo-ctl select{max-width:100%}
.bo-ctl .g .bo-info{flex:1 1 auto}
.bo-aviso.bo-bloq{border-left-color:var(--perigo);color:var(--text)}
.bo-aviso.bo-exig{border-left-color:var(--mod-bolus,#B5D65A);color:var(--text)}
.bo-sugerida{align-self:flex-start}
.bo-tab td.bo-amarela{color:var(--warn,#E1B23B);font-weight:700}
.bo-janela{max-height:92vh;overflow:auto}
.bo-janela .bo-tab{margin:2px 0}
.bo-corpo{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,1fr);
 gap:16px;align-items:start}
@media (max-width:980px){.bo-corpo{grid-template-columns:1fr}}
.bo-esq,.bo-dir{display:flex;flex-direction:column;gap:10px;min-width:0}
.bo-rotlinha{display:flex;flex-wrap:wrap;align-items:center;gap:8px;
 justify-content:space-between}
.bo-vistas{display:flex;gap:4px;flex-wrap:wrap}
.bo-vistas button{font-size:11.5px;padding:4px 9px}
.bo-palco3d{position:relative;width:100%;aspect-ratio:4/3;background:var(--img-fundo,#000);
 border:1px solid var(--line);border-radius:10px;overflow:hidden;cursor:grab;
 touch-action:none}
.bo-palco3d.b{aspect-ratio:1/1}
.bo-palco3d canvas{width:100%;height:100%;display:block}
.bo-palco3d .bo-dica{position:absolute;left:10px;bottom:8px;font-size:11px;
 color:var(--img-texto-fraco,#a3b1c6);pointer-events:none}
.bo-mprs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
.bo-mpr{display:flex;flex-direction:column;gap:4px;min-width:0}
.bo-mpr-cel{height:230px;display:flex;align-items:center;justify-content:center;
 background:var(--img-fundo,#000);border:1px solid var(--line);border-radius:8px;
 overflow:hidden}
.bo-mpr-palco{position:relative;touch-action:none}
.bo-mpr-palco img,.bo-mpr-palco svg{position:absolute;left:0;top:0;
 width:100%;height:100%;display:block}
.bo-mpr-palco img{object-fit:fill;image-rendering:auto}
.bo-mpr input[type=range]{width:100%}
.bo-cx{fill:rgba(181,214,90,.10);stroke:var(--mod-bolus,#B5D65A);
 stroke-width:1.6;vector-effect:non-scaling-stroke}
.bo-cx.fora{stroke-dasharray:5 4;fill:rgba(181,214,90,.04)}
.bo-mira{stroke:#7FD1D6;stroke-width:1;stroke-dasharray:3 4;
 vector-effect:non-scaling-stroke;opacity:.7}
.bo-alca{fill:var(--mod-bolus,#B5D65A)}
.bo-info{font-size:12.5px;color:var(--text-muted);font-variant-numeric:tabular-nums}
.bo-legenda{font-size:12px;color:var(--text-muted);line-height:1.55}
.bo-janelas{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
.bo-ctl{display:flex;flex-direction:column;gap:9px;background:var(--panel);
 border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.bo-ctl .g{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.bo-ctl .g > span:first-child,.bo-ctl .g > label.g-rot{min-width:128px;
 font-size:12.5px;color:var(--text-muted)}
#bo-suav-v{min-width:52px;text-align:right;font-variant-numeric:tabular-nums}
.bo-ctl input[type=number]{width:74px}
.bo-ctl input[type=range]{flex:1 1 90px;min-width:80px}
.bo-tab{width:100%;border-collapse:collapse;font-size:12.5px}
.bo-tab td{padding:4px 6px;border-bottom:1px solid var(--line)}
.bo-tab td:first-child{color:var(--text-muted)}
.bo-tab td:last-child{text-align:right;font-variant-numeric:tabular-nums;
 color:var(--text)}
.bo-avisos{display:flex;flex-direction:column;gap:6px}
.bo-aviso{border-left:3px solid var(--warn,#E1B23B);background:var(--panel-2);
 padding:7px 11px;border-radius:0 7px 7px 0;font-size:12.5px;line-height:1.55;
 color:var(--text-muted)}
.bo-bio{border-left-color:var(--perigo)}
.bo-velho{opacity:.55}
.bo-fronteira{font-size:12.5px;line-height:1.6;color:var(--text-muted);
 border-top:1px solid var(--line);padding-top:10px;margin:6px 0 0}
.bo-fronteira b{color:var(--text)}
.bo-veu{position:fixed;inset:0;background:rgba(2,6,14,.62);display:flex;
 align-items:center;justify-content:center;z-index:60;padding:16px}
.bo-veu[hidden]{display:none}
.bo-janela{max-width:620px;width:100%;background:var(--panel);
 border:1px solid var(--line-strong,var(--line));border-radius:12px;
 padding:18px 20px;display:flex;flex-direction:column;gap:10px;
 box-shadow:var(--sombra)}
.bo-janela h2{margin:0;font-size:17px}
.bo-janela p{margin:0;font-size:13.5px;line-height:1.6;color:var(--text-muted)}
.bo-ato{display:flex;gap:10px;align-items:flex-start;font-size:13.5px;
 line-height:1.55;color:var(--text);background:var(--panel-2);
 border:1px solid var(--line);border-radius:8px;padding:10px 12px;cursor:pointer}
.bo-ato input{margin-top:4px}
.bo-acoes{display:flex;gap:10px;justify-content:flex-end}
.bo-molde{display:flex;flex-direction:column;gap:9px;
 border-left:2px solid rgba(240,176,96,.6);padding:2px 0 2px 10px}
.bo-molde[hidden]{display:none}
.bo-tab tr.bo-sub td{padding-top:12px;color:var(--text);font-weight:700;
 text-align:left}
.bo-seg{display:flex;gap:4px;flex-wrap:wrap}
.bo-seg[hidden]{display:none}
.bo-seg button{font-size:11.5px;padding:4px 9px}
.bo-exps{display:flex;gap:8px;flex-wrap:wrap}
"""

JS = r"""
(function(){
'use strict';
function el(i){ return document.getElementById(i) }
function escreve(alvo, t){ if(window.uiTexto) window.uiTexto(alvo, t); else alvo.textContent = t }
var BO = {b:'', meta:null, caixa:null, janela:'pele', idx:{ax:0, co:0, sa:0},
  corpo:null, bolus:null, molde:null, ver:'ambos', peca:'bolus',
  res:null, r:'', velho:false, gerando:false, pedido:0,
  cam:{yaw:0, pitch:12, zoom:1}, camB:{yaw:0, pitch:12, zoom:1}, token:{e:0, d:0}};
var PLANOS = ['ax', 'co', 'sa'];
var USO_DA_VARREDURA = @USO_JS@;
var FRASE = @FRASE_JS@;
var SETA = @SETA_JS@;

function boPopup(){ return window.uiPopupSerie ? window.uiPopupSerie('bo_escolha') : null }
function msg(t, erro){
  var p = boPopup(), m = el((p && p.aberto()) ? 'bo-msg-ps' : 'bo-msg');
  escreve(m, t || ''); m.className = 'bo-msg' + (erro ? ' erro' : '');
}
function post(url, corpo){
  return fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify(corpo || {})}).then(function(r){ return r.json() });
}

el('bo-procurar').onclick = function(){
  if(!window.uiExplorador) return;
  window.uiExplorador({inicial: (el('bo-pasta').value || '').trim(), origem: el('bo-procurar'),
    aoUsar: function(c){ el('bo-pasta').value = c || ''; el('bo-listar').onclick() }});
};
el('bo-pasta').addEventListener('keydown', function(ev){ if(ev.key === 'Enter'){ ev.preventDefault(); el('bo-listar').onclick() } });
el('bo-listar').onclick = function(){
  var pasta = (el('bo-pasta').value || '').trim();
  if(!pasta){
    msg('informe a pasta', true);
    if(window.uiTremer) window.uiTremer(el('bo-pasta'));
    return;
  }
  if(!window.uiVarrerLista) return;
  msg('');
  el('bo-serie').innerHTML = ''; BO.lista = {}; liberarAbrir();
  var pedido = ++BO.pedido;
  window.uiVarrerLista({estado: 'bo-busca', uso: USO_DA_VARREDURA, chave: 'bolus',
    pasta: pasta, dias: 'bo_dias',
    pintar: function(linhas){ if(pedido === BO.pedido) boOpcoes(linhas) },
    aoFim: function(linhas){
      if(pedido !== BO.pedido) return;
      boOpcoes(linhas || []);
      if(!(linhas || []).length) msg('Nenhuma série nesta pasta.', true);
    },
    aoErro: function(m){ if(pedido === BO.pedido) msg(m, true) }});
};
function boOpcoes(linhas){
  var s = el('bo-serie');
  linhas.forEach(function(x){
    if(!x.b || BO.lista[x.b]) return;
    var o = document.createElement('option');
    o.value = x.b; o.textContent = x.rotulo + (x.recusada ? ' — ' + x.recusada : '');
    o.disabled = !!x.recusada; s.appendChild(o); BO.lista[x.b] = x;
  });
  var atual = s.selectedOptions[0];
  if(!atual || atual.disabled){
    var livre = [].slice.call(s.options).filter(function(o){ return !o.disabled });
    if(livre.length) s.value = livre[0].value;
  }
  if(window.radaiRetraduzir) window.radaiRetraduzir();
  liberarAbrir();
}
el('bo-serie').onchange = function(){ liberarAbrir() };

function boRotulo(b){
  var x = BO.lista && BO.lista[b];
  return x ? x.rotulo : '';
}
function boDoAcervo(linha){
  if(!linha || !linha.bilhete) return;
  msg('abrindo a série…');
  post('/api/bolus/acervo', {bilhete: linha.bilhete}).then(function(d){
    if(!d || d.erro || !d.b){ msg((d && d.erro) || 'a série não está mais no acervo', true); return }
    if(d.recusada){ msg(d.recusada, true); return }
    var dt = String(linha.date || '');
    if(dt.length >= 8) dt = dt.slice(6, 8) + '/' + dt.slice(4, 6) + '/' + dt.slice(0, 4);
    d.rotulo = [dt, linha.pid, linha.modalidade].filter(function(x){ return x }).join(' · ') || d.rotulo;
    BO.lista = BO.lista || {}; BO.lista[d.b] = d;
    boAbrir(d.b);
  }).catch(function(e){ msg(String(e), true) });
}
el('bo-abrir').onclick = function(){ boAbrir(el('bo-serie').value) };
function boAbrir(b){
  if(!b) return;
  msg('abrindo a série…');
  el('bo-abrir').disabled = true;
  post('/api/bolus/abrir', {b: b}).then(function(d){
    liberarAbrir();
    if(d.erro){ msg(d.erro, true); return }
    var pp = boPopup(); if(pp) pp.fechar();
    if(window.uiCartaoRotulo) window.uiCartaoRotulo('bo-cartao', boRotulo(b));
    BO.b = b; BO.meta = d; BO.caixa = d.caixa; BO.res = null; BO.bolus = null; BO.r = '';
    BO.idx = {ax: Math.round(((d.caixa.z0 + d.caixa.z1) / 2) / d.esp[2]),
              co: Math.round(((d.caixa.y0 + d.caixa.y1) / 2) / d.esp[1]),
              sa: Math.round(((d.caixa.x0 + d.caixa.x1) / 2) / d.esp[0])};
    el('bo-corpo').style.display = '';
    PLANOS.forEach(prepararPlano);
    limparResultado();
    msg(d.sem_mesa ? '' : 'contorno externo sem remoção de mesa', !d.sem_mesa);
    fetch('/api/bolus/volume?b=' + encodeURIComponent(b) + '&qual=corpo')
      .then(function(r){ return r.arrayBuffer() }).then(function(buf){
        BO.corpo = vol(d.previa, buf); desenharE(1);
      });
  }).catch(function(e){ liberarAbrir(); msg(String(e), true) });
}
if(el('bo_acervo') && window.uiTabelaAcervo)
  window.uiTabelaAcervo('bo_acervo', {aoAbrir: function(linha){ boDoAcervo(linha) },
    filtro: function(l){ return !l.modalidade || l.modalidade === 'CT' }});

function zmax(){ return (BO.meta.forma[2] - 1) * BO.meta.esp[2] }
function geo(pl){
  var f = BO.meta.forma, e = BO.meta.esp;
  if(pl === 'ax') return {vb:[-e[0]/2, -e[1]/2, f[0]*e[0], f[1]*e[1]], n:f[2]};
  if(pl === 'co') return {vb:[-e[0]/2, -e[2]/2, f[0]*e[0], f[2]*e[2]], n:f[1]};
  return {vb:[-e[1]/2, -e[2]/2, f[1]*e[1], f[2]*e[2]], n:f[0]};
}
function ret(pl){
  var c = BO.caixa, zm = zmax();
  if(pl === 'ax') return [c.x0, c.y0, c.x1, c.y1];
  if(pl === 'co') return [c.x0, zm - c.z1, c.x1, zm - c.z0];
  return [c.y0, zm - c.z1, c.y1, zm - c.z0];
}
function porRet(pl, a0, b0, a1, b1){
  var c = BO.caixa, zm = zmax();
  if(pl === 'ax'){ c.x0 = a0; c.x1 = a1; c.y0 = b0; c.y1 = b1 }
  else if(pl === 'co'){ c.x0 = a0; c.x1 = a1; c.z0 = zm - b1; c.z1 = zm - b0 }
  else { c.y0 = a0; c.y1 = a1; c.z0 = zm - b1; c.z1 = zm - b0 }
  var ext = [(BO.meta.forma[0]-1)*BO.meta.esp[0], (BO.meta.forma[1]-1)*BO.meta.esp[1], zm];
  ['x', 'y', 'z'].forEach(function(k, i){
    var a = Math.max(0, Math.min(c[k+'0'], c[k+'1'])), b = Math.min(ext[i], Math.max(c[k+'0'], c[k+'1']));
    if(b - a < 10){ if(a + 10 <= ext[i]) b = a + 10; else a = b - 10 }
    c[k+'0'] = a; c[k+'1'] = b;
  });
}
function prepararPlano(pl){
  var g = geo(pl), r = el('bo-r-' + pl);
  r.min = 0; r.max = g.n - 1; r.value = Math.max(0, Math.min(g.n - 1, BO.idx[pl]));
  BO.idx[pl] = +r.value;
  var svg = el('bo-s-' + pl);
  svg.setAttribute('viewBox', g.vb.join(' '));
  ajustarPalco(pl); carregarCorte(pl); desenharCaixas();
}
function ajustarPalco(pl){
  var g = geo(pl), cel = el('bo-p-' + pl).parentNode, p = el('bo-p-' + pl);
  var W = cel.clientWidth - 4, H = cel.clientHeight - 4;
  var k = Math.min(W / g.vb[2], H / g.vb[3]);
  p.style.width = Math.max(10, Math.floor(g.vb[2] * k)) + 'px';
  p.style.height = Math.max(10, Math.floor(g.vb[3] * k)) + 'px';
}
var _tCorte = {};
function carregarCorte(pl){
  clearTimeout(_tCorte[pl]);
  _tCorte[pl] = setTimeout(function(){
    el('bo-i-' + pl).src = '/api/bolus/corte?b=' + encodeURIComponent(BO.b) + '&plano=' + pl +
      '&i=' + BO.idx[pl] + '&jan=' + BO.janela + (BO.r && !BO.velho ? '&r=' + BO.r : '');
  }, 60);
}
PLANOS.forEach(function(pl){
  el('bo-r-' + pl).oninput = function(){ BO.idx[pl] = +this.value; carregarCorte(pl); desenharCaixas() };
});
[].forEach.call(document.querySelectorAll('[data-jan]'), function(bt){
  bt.onclick = function(){
    BO.janela = bt.getAttribute('data-jan');
    [].forEach.call(document.querySelectorAll('[data-jan]'), function(x){ x.classList.toggle('on', x === bt) });
    if(BO.meta) PLANOS.forEach(carregarCorte);
  };
});
function NS(t){ return document.createElementNS('http://www.w3.org/2000/svg', t) }
function dentroDoCorte(pl){
  var c = BO.caixa, e = BO.meta.esp;
  if(pl === 'ax'){ var z = BO.idx.ax * e[2]; return z >= c.z0 && z <= c.z1 }
  if(pl === 'co'){ var y = BO.idx.co * e[1]; return y >= c.y0 && y <= c.y1 }
  var x = BO.idx.sa * e[0]; return x >= c.x0 && x <= c.x1;
}
function desenharCaixas(){
  if(!BO.meta) return;
  var e = BO.meta.esp, zm = zmax();
  PLANOS.forEach(function(pl){
    var svg = el('bo-s-' + pl), g = geo(pl), r = ret(pl);
    while(svg.firstChild) svg.removeChild(svg.firstChild);
    var mx, my;
    if(pl === 'ax'){ mx = BO.idx.sa * e[0]; my = BO.idx.co * e[1] }
    else if(pl === 'co'){ mx = BO.idx.sa * e[0]; my = zm - BO.idx.ax * e[2] }
    else { mx = BO.idx.co * e[1]; my = zm - BO.idx.ax * e[2] }
    [[mx, g.vb[1], mx, g.vb[1] + g.vb[3]], [g.vb[0], my, g.vb[0] + g.vb[2], my]].forEach(function(l){
      var ln = NS('line'); ln.setAttribute('x1', l[0]); ln.setAttribute('y1', l[1]);
      ln.setAttribute('x2', l[2]); ln.setAttribute('y2', l[3]);
      ln.setAttribute('class', 'bo-mira'); svg.appendChild(ln);
    });
    var rc = NS('rect');
    rc.setAttribute('x', r[0]); rc.setAttribute('y', r[1]);
    rc.setAttribute('width', r[2] - r[0]); rc.setAttribute('height', r[3] - r[1]);
    rc.setAttribute('class', 'bo-cx' + (dentroDoCorte(pl) ? '' : ' fora'));
    svg.appendChild(rc);
    var s = g.vb[2] / Math.max(1, svg.clientWidth) * 5;
    [[r[0], r[1]], [r[2], r[1]], [r[0], r[3]], [r[2], r[3]]].forEach(function(p){
      var a = NS('rect'); a.setAttribute('x', p[0] - s/2); a.setAttribute('y', p[1] - s/2);
      a.setAttribute('width', s); a.setAttribute('height', s); a.setAttribute('class', 'bo-alca');
      svg.appendChild(a);
    });
  });
  var c = BO.caixa;
  escreve(el('bo-caixa-mm'), Math.round(c.x1 - c.x0) + ' × ' + Math.round(c.y1 - c.y0) + ' × ' +
    Math.round(c.z1 - c.z0) + ' mm');
}
function pontoSvg(svg, ev){
  var p = svg.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
  return p.matrixTransform(svg.getScreenCTM().inverse());
}
function acerto(pl, svg, p){
  var r = ret(pl), g = geo(pl), tol = g.vb[2] / Math.max(1, svg.clientWidth) * 7;
  var dentroA = p.x > r[0] - tol && p.x < r[2] + tol, dentroB = p.y > r[1] - tol && p.y < r[3] + tol;
  var h = {a0: Math.abs(p.x - r[0]) < tol && dentroB, a1: Math.abs(p.x - r[2]) < tol && dentroB,
           b0: Math.abs(p.y - r[1]) < tol && dentroA, b1: Math.abs(p.y - r[3]) < tol && dentroA};
  if(h.a0 || h.a1 || h.b0 || h.b1) return h;
  if(p.x > r[0] && p.x < r[2] && p.y > r[1] && p.y < r[3]) return {mover: true};
  return null;
}
function cursorDe(h){
  if(!h) return 'crosshair';
  if(h.mover) return 'move';
  if((h.a0 && h.b0) || (h.a1 && h.b1)) return 'nwse-resize';
  if((h.a0 && h.b1) || (h.a1 && h.b0)) return 'nesw-resize';
  return (h.a0 || h.a1) ? 'ew-resize' : 'ns-resize';
}
PLANOS.forEach(function(pl){
  var svg = el('bo-s-' + pl), arr = null;
  svg.addEventListener('pointerdown', function(ev){
    if(!BO.meta) return;
    var p = pontoSvg(svg, ev), h = acerto(pl, svg, p);
    if(!h) return;
    arr = {h: h, p0: p, r0: ret(pl)};
    svg.setPointerCapture(ev.pointerId); ev.preventDefault();
  });
  svg.addEventListener('pointermove', function(ev){
    if(!BO.meta) return;
    var p = pontoSvg(svg, ev);
    if(!arr){ svg.style.cursor = cursorDe(acerto(pl, svg, p)); return }
    var dx = p.x - arr.p0.x, dy = p.y - arr.p0.y, r = arr.r0.slice(), h = arr.h;
    if(h.mover){ r[0] += dx; r[2] += dx; r[1] += dy; r[3] += dy }
    else { if(h.a0) r[0] += dx; if(h.a1) r[2] += dx; if(h.b0) r[1] += dy; if(h.b1) r[3] += dy }
    porRet(pl, r[0], r[1], r[2], r[3]);
    caixaMudou();
  });
  function soltar(){ if(arr){ arr = null; desenharE(1) } }
  svg.addEventListener('pointerup', soltar);
  svg.addEventListener('pointercancel', soltar);
});
function caixaMudou(){
  desenharCaixas();
  marcarVelho();
  desenharE(0.34);
}

function cruz(a, b){ return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]] }
function norma(a){ var n = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0]/n, a[1]/n, a[2]/n] }
function vol(m, buf){ return {nx:m.forma[0], ny:m.forma[1], nz:m.forma[2], sp:m.sp, off:m.off, d:new Uint8Array(buf)} }
function caixaDe(v){
  var h = v.sp / 2;
  return [v.off[0]-h, v.off[1]-h, v.off[2]-h, v.off[0]+(v.nx-0.5)*v.sp, v.off[1]+(v.ny-0.5)*v.sp, v.off[2]+(v.nz-0.5)*v.sp];
}
function laje(o, d, bb){
  var t0 = -1e9, t1 = 1e9;
  for(var k = 0; k < 3; k++){
    if(Math.abs(d[k]) < 1e-12){ if(o[k] < bb[k] || o[k] > bb[k+3]) return null; continue }
    var a = (bb[k] - o[k]) / d[k], b = (bb[k+3] - o[k]) / d[k];
    if(a > b){ var t = a; a = b; b = t }
    if(a > t0) t0 = a; if(b < t1) t1 = b;
  }
  return t1 > Math.max(t0, 0) ? [Math.max(t0, 0), t1] : null;
}
function tri(v, X, Y, Z){ return tri255(v, X, Y, Z) / 255 }
function tri255(v, X, Y, Z){
  var fx = (X - v.off[0]) / v.sp, fy = (Y - v.off[1]) / v.sp, fz = (Z - v.off[2]) / v.sp;
  var x0 = Math.floor(fx), y0 = Math.floor(fy), z0 = Math.floor(fz);
  var ax = fx - x0, ay = fy - y0, az = fz - z0;
  function g(x, y, z){
    if(x < 0 || y < 0 || z < 0 || x >= v.nx || y >= v.ny || z >= v.nz) return 0;
    return v.d[(z * v.ny + y) * v.nx + x];
  }
  var c00 = g(x0, y0, z0) * (1 - ax) + g(x0 + 1, y0, z0) * ax;
  var c10 = g(x0, y0 + 1, z0) * (1 - ax) + g(x0 + 1, y0 + 1, z0) * ax;
  var c01 = g(x0, y0, z0 + 1) * (1 - ax) + g(x0 + 1, y0, z0 + 1) * ax;
  var c11 = g(x0, y0 + 1, z0 + 1) * (1 - ax) + g(x0 + 1, y0 + 1, z0 + 1) * ax;
  return (c00 * (1 - ay) + c10 * ay) * (1 - az) + (c01 * (1 - ay) + c11 * ay) * az;
}
function refinar(v, o, d, t, passo){
  var a = t - passo, b = t;
  for(var r = 0; r < 4 && tri(v, o[0] + d[0]*a, o[1] + d[1]*a, o[2] + d[2]*a) >= 0.5; r++) a -= passo;
  for(var k = 0; k < 8; k++){
    var m = (a + b) / 2;
    if(tri(v, o[0] + d[0]*m, o[1] + d[1]*m, o[2] + d[2]*m) >= 0.5) b = m; else a = m;
  }
  return b;
}
function amostra(v, X, Y, Z){
  var ix = Math.round((X - v.off[0]) / v.sp), iy = Math.round((Y - v.off[1]) / v.sp), iz = Math.round((Z - v.off[2]) / v.sp);
  if(ix < 0 || iy < 0 || iz < 0 || ix >= v.nx || iy >= v.ny || iz >= v.nz) return 0;
  return v.d[(iz * v.ny + iy) * v.nx + ix] >= 128 ? 1 : 0;
}
function normalVol(v, P, cam){
  var h = v.sp * 0.6;
  var gx = tri255(v, P[0] + h, P[1], P[2]) - tri255(v, P[0] - h, P[1], P[2]);
  var gy = tri255(v, P[0], P[1] + h, P[2]) - tri255(v, P[0], P[1] - h, P[2]);
  var gz = tri255(v, P[0], P[1], P[2] + h) - tri255(v, P[0], P[1], P[2] - h);
  var n = norma([-gx, -gy, -gz]);
  return [n[0]*cam.right[0] + n[1]*cam.right[1] + n[2]*cam.right[2],
          n[0]*cam.up[0] + n[1]*cam.up[1] + n[2]*cam.up[2],
          -(n[0]*cam.dir[0] + n[1]*cam.dir[1] + n[2]*cam.dir[2])];
}
function camera(c){
  var ya = c.yaw * Math.PI / 180, pi = c.pitch * Math.PI / 180;
  var dir = [Math.sin(ya), Math.cos(ya), 0], up = [0, 0, 1];
  var right = norma(cruz(dir, up));
  var cp = Math.cos(pi), sp = Math.sin(pi);
  dir = norma([dir[0]*cp + up[0]*sp, dir[1]*cp + up[1]*sp, dir[2]*cp + up[2]*sp]);
  up = norma(cruz(right, dir));
  return {dir: dir, right: right, up: up, zoom: c.zoom || 1};
}
function lancar(cena, cam, W, H, token, qual, pronto){
  var alvo = cena.bb, C = [(alvo[0]+alvo[3])/2, (alvo[1]+alvo[4])/2, (alvo[2]+alvo[5])/2];
  var diag = Math.hypot(alvo[3]-alvo[0], alvo[4]-alvo[1], alvo[5]-alvo[2]);
  var escala = diag * 1.02 / Math.min(W, H) / (cam.zoom || 1);
  var pp = new Float32Array(W*H).fill(-1), pb = new Float32Array(W*H).fill(-1);
  var np_ = new Float32Array(W*H*3), nb = new Float32Array(W*H*3);
  var ta = new Float32Array(W*H).fill(-1), tb = new Float32Array(W*H).fill(-1), dentro = new Uint8Array(W*H);
  var pac = cena.pac, bol = cena.bol, cx = cena.cx;
  var bbP = pac ? caixaDe(pac) : null, bbB = bol ? caixaDe(bol) : null;
  var passoP = pac ? pac.sp * 0.85 : 1e9, passoB = bol ? bol.sp * 0.8 : 1e9;
  var py = 0, d = cam.dir;
  function lote(){
    if(BO.token[qual] !== token) return;
    var t0 = performance.now();
    for(; py < H; py++){
      if(performance.now() - t0 > 28){ setTimeout(lote, 0); return }
      var v = (H/2 - py) * escala;
      for(var px = 0; px < W; px++){
        var u = (px - W/2) * escala, i = py*W + px;
        var o = [C[0] + cam.right[0]*u + cam.up[0]*v - d[0]*diag,
                 C[1] + cam.right[1]*u + cam.up[1]*v - d[1]*diag,
                 C[2] + cam.right[2]*u + cam.up[2]*v - d[2]*diag];
        var fp = bbP ? laje(o, d, bbP) : null, fb = bbB ? laje(o, d, bbB) : null;
        if(cx){ var fc = laje(o, d, cx); if(fc){ ta[i] = fc[0]; tb[i] = fc[1] } }
        var ini = 1e9, fim = -1e9;
        if(fp){ ini = Math.min(ini, fp[0]); fim = Math.max(fim, fp[1]) }
        if(fb){ ini = Math.min(ini, fb[0]); fim = Math.max(fim, fb[1]) }
        if(fim < ini) continue;
        var t = ini, achouB = -1;
        while(t <= fim){
          var X = o[0] + d[0]*t, Y = o[1] + d[1]*t, Z = o[2] + d[2]*t;
          var emB = fb && t >= fb[0] && t <= fb[1];
          if(achouB < 0 && emB && amostra(bol, X, Y, Z)){
            achouB = refinar(bol, o, d, t, passoB); pb[i] = achouB;
            var nB = normalVol(bol, [o[0] + d[0]*achouB, o[1] + d[1]*achouB, o[2] + d[2]*achouB], cam);
            nb[3*i] = nB[0]; nb[3*i+1] = nB[1]; nb[3*i+2] = nB[2];
            if(!pac) break }
          if(pac && fp && t >= fp[0] && amostra(pac, X, Y, Z)){
            pp[i] = refinar(pac, o, d, t, emB ? passoB : passoP);
            var nP = normalVol(pac, [o[0] + d[0]*pp[i], o[1] + d[1]*pp[i], o[2] + d[2]*pp[i]], cam);
            np_[3*i] = nP[0]; np_[3*i+1] = nP[1]; np_[3*i+2] = nP[2];
            if(cx){ dentro[i] = (X >= cx[0] && X <= cx[3] && Y >= cx[1] && Y <= cx[4] && Z >= cx[2] && Z <= cx[5]) ? 1 : 0 }
            break }
          t += emB ? passoB : passoP;
        }
      }
    }
    pronto({pp: pp, pb: pb, np: np_, nb: nb, ta: ta, tb: tb, dentro: dentro, W: W, H: H, escala: escala, C: C, diag: diag});
  }
  lote();
}
var LUZ = norma([-0.42, 0.5, 0.76]);
function luz(n, prox){
  var lam = Math.max(0, n[0]*LUZ[0] + n[1]*LUZ[1] + n[2]*LUZ[2]);
  var dif = Math.pow(lam, 0.82), esp = Math.pow(lam, 34) * 0.5;
  return {k: Math.min(1, 0.13 + 0.2*prox + dif*0.86 + esp), borda: Math.pow(1 - n[2], 2.4) * 0.42};
}
function frio(k, borda){
  var R, G, B;
  if(k < 0.5){ var q = k/0.5; R = 11 + q*62; G = 27 + q*96; B = 51 + q*122 }
  else { var q2 = (k-0.5)/0.5; R = 73 + q2*163; G = 123 + q2*128; B = 173 + q2*77 }
  return [R + borda*12, G + borda*132, B + borda*168];
}
function lima(k, borda){
  var R, G, B;
  if(k < 0.5){ var q = k/0.5; R = 34 + q*110; G = 44 + q*132; B = 12 + q*40 }
  else { var q2 = (k-0.5)/0.5; R = 144 + q2*101; G = 176 + q2*76; B = 52 + q2*148 }
  return [R + borda*60, G + borda*70, B + borda*40];
}
function cera(k, borda){
  var R, G, B;
  if(k < 0.5){ var q = k/0.5; R = 58 + q*132; G = 36 + q*98; B = 14 + q*48 }
  else { var q2 = (k-0.5)/0.5; R = 190 + q2*62; G = 134 + q2*86; B = 62 + q2*112 }
  return [R + borda*50, G + borda*48, B + borda*36];
}
function pintar(canvas, m, cena, cam){
  var rampaP = cena.rampaP || frio, rampaB = cena.rampaB || lima;
  var alfa = cena.alfa || 0.62, nevoa = cena.nevoa !== false;
  var W = m.W, H = m.H, img = new Uint8ClampedArray(W*H*4);
  var faixaP = [1e9, -1e9], faixaB = [1e9, -1e9];
  for(var i = 0; i < W*H; i++){
    if(m.pp[i] >= 0){ faixaP[0] = Math.min(faixaP[0], m.pp[i]); faixaP[1] = Math.max(faixaP[1], m.pp[i]) }
    if(m.pb[i] >= 0){ faixaB[0] = Math.min(faixaB[0], m.pb[i]); faixaB[1] = Math.max(faixaB[1], m.pb[i]) }
  }
  var fP = Math.max(1, faixaP[1] - faixaP[0]), fB = Math.max(1, faixaB[1] - faixaB[0]);
  for(var y = 0; y < H; y++) for(var x = 0; x < W; x++){
    var i2 = y*W + x, o = i2*4, cor;
    var zp = m.pp[i2], zb = m.pb[i2];
    if(zp < 0 && zb < 0){
      var rr = Math.hypot((x - W*0.5)/(W*0.5), (y - H*0.46)/(H*0.5)), f = Math.max(0, 1 - rr*0.82);
      cor = [4 + 10*f, 8 + 20*f, 18 + 42*f];
      [[W*0.455, H*0.4, 1.15, 0.5, 0.16], [W*0.36, H*0.47, 0.95, 0.36, -0.3]].forEach(function(an){
        var dx = x - W*0.5, dy = y - H*0.47;
        var rx = dx*Math.cos(an[4]) - dy*Math.sin(an[4]), ry = dx*Math.sin(an[4]) + dy*Math.cos(an[4]);
        var q = Math.hypot(rx/an[0], ry/an[1]), dist = Math.abs(q - 1) * Math.min(an[0], an[1]);
        if(dist < an[2]*2.4){ var it = Math.max(0, 1 - dist/(an[2]*2.4)) * an[3] * 0.6, mx = 0.5 + rx/(an[0]*2);
          cor[0] += it*(10 + 26*mx); cor[1] += it*(42 + 169*mx); cor[2] += it*(107 + 131*mx) }
      });
    } else {
      var base = null;
      if(zp >= 0){
        var proxP = 1 - (zp - faixaP[0])/fP;
        var L = luz([m.np[3*i2], m.np[3*i2+1], m.np[3*i2+2]], proxP);
        base = rampaP(L.k, L.borda);
        var nev = nevoa ? 0.72 + 0.28 * proxP : 1;
        base = [base[0]*nev + 5*(1-nev), base[1]*nev + 12*(1-nev), base[2]*nev + 28*(1-nev)];
        if(m.dentro[i2]){ base = [base[0]*0.78 + 181*0.22, base[1]*0.78 + 214*0.22, base[2]*0.78 + 90*0.22] }
      }
      if(zb >= 0 && (zp < 0 || zb <= zp + 0.5)){
        var L2 = luz([m.nb[3*i2], m.nb[3*i2+1], m.nb[3*i2+2]], 1 - (zb - faixaB[0])/fB);
        var bc = rampaB(L2.k, L2.borda), a = base ? alfa : 1.0;
        cor = base ? [base[0]*(1-a) + bc[0]*a, base[1]*(1-a) + bc[1]*a, base[2]*(1-a) + bc[2]*a] : bc;
      } else cor = base;
    }
    if(m.ta[i2] >= 0){
      var ts = zp >= 0 ? zp : 1e9;
      if(m.ta[i2] < ts) cor = [cor[0]*0.86 + 230*0.14, cor[1]*0.86 + 240*0.14, cor[2]*0.86 + 250*0.14];
      if(m.tb[i2] < ts) cor = [cor[0]*0.92 + 200*0.08, cor[1]*0.92 + 220*0.08, cor[2]*0.92 + 240*0.08];
    }
    img[o] = cor[0]; img[o+1] = cor[1]; img[o+2] = cor[2]; img[o+3] = 255;
  }
  canvas.width = W; canvas.height = H;
  var g = canvas.getContext('2d');
  g.putImageData(new ImageData(img, W, H), 0, 0);
  if(cena.cx){
    var b = cena.cx, P = [];
    for(var k = 0; k < 8; k++) P.push([b[(k&1) ? 3 : 0], b[(k&2) ? 4 : 1], b[(k&4) ? 5 : 2]]);
    function tela(p){ var q = [p[0]-m.C[0], p[1]-m.C[1], p[2]-m.C[2]];
      return [W/2 + (q[0]*cam.right[0] + q[1]*cam.right[1] + q[2]*cam.right[2]) / m.escala,
              H/2 - (q[0]*cam.up[0] + q[1]*cam.up[1] + q[2]*cam.up[2]) / m.escala] }
    g.strokeStyle = 'rgba(214,236,160,.85)'; g.lineWidth = Math.max(1, W/520);
    [[0,1],[2,3],[4,5],[6,7],[0,2],[1,3],[4,6],[5,7],[0,4],[1,5],[2,6],[3,7]].forEach(function(a){
      var p = tela(P[a[0]]), q = tela(P[a[1]]); g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke();
    });
  }
}
function desenhar(qual, canvas, cena, cam, q){
  if(!cena.bb) return;
  var W = Math.max(40, Math.round(canvas.clientWidth * q)), H = Math.max(30, Math.round(canvas.clientHeight * q));
  var token = ++BO.token[qual];
  lancar(cena, camera(cam), W, H, token, qual, function(m){
    if(BO.token[qual] === token) pintar(canvas, m, cena, camera(cam));
  });
}
function caixaMm(){ var c = BO.caixa; return [c.x0, c.y0, c.z0, c.x1, c.y1, c.z1] }
var _tE = null;
function desenharE(q){
  if(!BO.corpo) return;
  var cena = {pac: BO.corpo, bol: BO.velho ? null : BO.bolus, cx: caixaMm(), bb: caixaDe(BO.corpo)};
  desenhar('e', el('bo-c3d'), cena, BO.cam, q);
  if(q < 1){ clearTimeout(_tE); _tE = setTimeout(function(){ desenharE(1) }, 260) }
}
function cenaD(){
  var mo = BO.molde, bo = BO.bolus;
  if(mo && BO.ver === 'molde') return {pac: null, bol: mo, cx: null, bb: caixaDe(mo), rampaB: cera};
  if(mo && BO.ver === 'ambos') return {pac: bo, bol: mo, cx: null, bb: caixaDe(mo),
    rampaP: lima, rampaB: cera, alfa: 0.42, nevoa: false};
  return {pac: null, bol: bo, cx: null, bb: caixaDe(bo)};
}
function desenharD(q){
  if(!BO.bolus) return;
  desenhar('d', el('bo-c3b'), cenaD(), BO.camB, q);
}
[].forEach.call(document.querySelectorAll('[data-ver]'), function(bt){
  bt.onclick = function(){
    BO.ver = bt.getAttribute('data-ver');
    [].forEach.call(document.querySelectorAll('[data-ver]'), function(x){ x.classList.toggle('on', x === bt); x.setAttribute('aria-pressed', x === bt ? 'true' : 'false') });
    desenharD(1);
  };
});
function girar(canvas, cam, redesenha){
  var ult = null;
  canvas.addEventListener('pointerdown', function(ev){ ult = [ev.clientX, ev.clientY]; canvas.setPointerCapture(ev.pointerId) });
  canvas.addEventListener('pointermove', function(ev){
    if(!ult) return;
    cam.yaw += (ev.clientX - ult[0]) * 0.5;
    cam.pitch = Math.max(-85, Math.min(85, cam.pitch + (ev.clientY - ult[1]) * 0.4));
    ult = [ev.clientX, ev.clientY]; redesenha(0.34);
  });
  function fim(){ if(ult){ ult = null; redesenha(1) } }
  canvas.addEventListener('pointerup', fim); canvas.addEventListener('pointercancel', fim);
  var tz = null;
  canvas.addEventListener('wheel', function(ev){
    ev.preventDefault();
    cam.zoom = Math.max(0.5, Math.min(8, (cam.zoom || 1) * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
    redesenha(0.34); clearTimeout(tz); tz = setTimeout(function(){ redesenha(1) }, 220);
  }, {passive: false});
  canvas.addEventListener('dblclick', function(){ cam.zoom = 1; redesenha(1) });
}
girar(el('bo-c3d'), BO.cam, desenharE);
girar(el('bo-c3b'), BO.camB, desenharD);
var VISTA = {ant:[0, 12], post:[180, 12], dir:[90, 12], esq:[-90, 12], sup:[0, -85], inf:[0, 85]};
var VISTA_ABERTURA = {superior:[25, -40], inferior:[25, 40], esquerda:[-55, 15], direita:[55, 15]};
[].forEach.call(document.querySelectorAll('[data-vista]'), function(bt){
  bt.onclick = function(){ var v = VISTA[bt.getAttribute('data-vista')]; BO.cam.yaw = v[0]; BO.cam.pitch = v[1]; desenharE(1) };
});
window.addEventListener('resize', function(){ if(BO.meta){ PLANOS.forEach(ajustarPalco); desenharCaixas(); desenharE(1); desenharD(1) } });

function parametros(){
  var modo = document.querySelector('input[name=bo-modo]:checked').value;
  var p = {b: BO.b, caixa: BO.caixa, modo: modo,
          espessura: modo === 'caixa' ? null : +el('bo-esp').value, suavizacao: +el('bo-suav').value,
          direcao: el('bo-dir').value, marcas: el('bo-marcas').checked,
          molde: el('bo-molde').checked};
  if(p.molde){ p.casca = +el('bo-casca').value; p.abertura = el('bo-abertura').value }
  return p;
}
function liberarAbrir(){
  var o = el('bo-serie').selectedOptions[0];
  el('bo-abrir').disabled = BO.gerando || !o || o.disabled;
}
el('bo-suav').oninput = function(){ escreve(el('bo-suav-v'), (+this.value).toFixed(1) + ' mm'); marcarVelho() };
escreve(el('bo-suav-v'), (+el('bo-suav').value).toFixed(1) + ' mm');
['bo-esp', 'bo-dir', 'bo-marcas', 'bo-molde', 'bo-casca', 'bo-abertura'].forEach(function(i){ el(i).addEventListener('change', marcarVelho) });
el('bo-molde').addEventListener('change', function(){ el('bo-molde-ctl').hidden = !this.checked });
[].forEach.call(document.querySelectorAll('input[name=bo-modo]'), function(r){ r.addEventListener('change', function(){
  el('bo-esp').disabled = (this.value === 'caixa'); el('bo-esp-caixa').hidden = (this.value !== 'caixa'); marcarVelho() }) });
function marcarVelho(){
  if(!BO.res) return;
  BO.velho = true; el('bo-exportar').disabled = true; el('bo-exportar-molde').disabled = true;
  el('bo-ap-exportar').disabled = true;
  el('bo-resultado').classList.add('bo-velho');
  escreve(el('bo-estado'), 'A caixa ou os parâmetros mudaram: gere de novo para exportar.');
}
function mostrarMolde(tem){
  el('bo-ver').hidden = !tem; el('bo-rot-b').hidden = !!tem;
}
function limparResultado(){
  BO.res = null; BO.bolus = null; BO.molde = null; BO.velho = false; BO.r = '';
  el('bo-exportar').disabled = true; el('bo-exportar-molde').disabled = true;
  el('bo-ap-exportar').disabled = true;
  el('bo-estado').classList.remove('erro');
  mostrarMolde(false);
  el('bo-resultado').classList.remove('bo-velho');
  el('bo-tab').innerHTML = ''; el('bo-avisos').innerHTML = ''; el('bo-bio').hidden = true;
  escreve(el('bo-estado'), '');
  var g = el('bo-c3b').getContext('2d'); g.clearRect(0, 0, el('bo-c3b').width, el('bo-c3b').height);
}
function linha(rot, val){ return '<tr><td>' + rot + '</td><td>' + val + '</td></tr>' }
function num(v, d){ return (v == null || isNaN(v)) ? '—' : (+v).toFixed(d == null ? 1 : d).replace('.', ',') }
var ABERTURA = {externa:'externa', superior:'superior', inferior:'inferior', esquerda:'esquerda', direita:'direita'};
function linhasDoMolde(mo){
  if(!mo) return '';
  var e = mo.espessura || {}, mm = mo.malha || {}, it = mo.interior || {};
  return '<tr class="bo-sub"><td colspan="2">' + 'molde' + '</td></tr>' +
    linha('casca pedida', mo.casca_mm + ' mm') +
    linha('casca medida (mín · mediana · máx)', num(e.min, 2) + ' · ' + num(e.mediana, 2) + ' · ' + num(e.max, 2) + ' mm') +
    linha('abertura', (ABERTURA[mo.abertura] || mo.abertura) + ' · ' + num(mo.abertura_mm2 / 100, 1) + ' cm²') +
    linha('interior igual ao bólus (vértices)', (it.vertices_iguais || 0).toLocaleString() + ' / ' + (it.vertices_internos || 0).toLocaleString()) +
    linha('malha fechada', mm.fechada ? 'sim' : 'não') +
    linha('ida e volta STL → voxel (DSC)', num(mo.dsc_ida_volta, 4)) +
    linha('volume do material', num(mo.volume_cm3) + ' cm³') +
    linha('triângulos', (mm.triangulos || 0).toLocaleString()) +
    linha('peças', mo.pecas);
}
el('bo-gerar').onclick = function(){
  if(!BO.meta) return;
  var b = BO.b;
  var bt = el('bo-gerar'); bt.disabled = true;
  BO.gerando = true; el('bo-abrir').disabled = true;
  escreve(el('bo-estado'), 'gerando o bólus…');
  var apaga = brilho('gerando o bólus…');
  post('/api/bolus/gerar', parametros()).then(function(d){
    apaga(); bt.disabled = false; BO.gerando = false; liberarAbrir();
    if(BO.b !== b) return;
    if(d.erro){ escreve(el('bo-estado'), d.erro); return }
    BO.res = d; BO.r = d.r; BO.velho = false; BO.molde = null;
    el('bo-resultado').classList.remove('bo-velho');
    var e = d.espessura || {}, m = d.malha || {};
    var DIR = {ant:'anterior', post:'posterior', dir:'direita', esq:'esquerda', sup:'superior', inf:'inferior'};
    el('bo-tab').innerHTML =
      linha('espessura mínima', num(e.min) + ' mm') + linha('espessura mediana', num(e.mediana) + ' mm') +
      linha('espessura máxima', num(e.max) + ' mm') + linha('volume do material', num(d.volume_cm3) + ' cm³') +
      linha('dimensões', (d.dimensoes_mm || []).map(function(v){ return Math.round(v) }).join(' × ') + ' mm') +
      linha('malha fechada', m.fechada ? 'sim' : 'não') +
      linha('ida e volta STL → voxel (DSC)', num(d.dsc_ida_volta, 4)) +
      linha('triângulos', (m.triangulos || 0).toLocaleString()) +
      linha('peças', d.pecas) + linha('grade de trabalho', num(d.grade_mm, 2) + ' mm') +
      linha('direção de colocação', DIR[d.direcao] || d.direcao) +
      linha('marcas de lado', d.marcas && d.marcas.colocadas ? (d.marcas.letra + ' ' + SETA) : '—') +
      linha('tempo', num(d.tempo_s) + ' s') + linhasDoMolde(d.molde);
    var av = el('bo-avisos'); av.innerHTML = '';
    (d.avisos || []).concat((d.molde || {}).avisos || []).forEach(function(t){ var p = document.createElement('div'); p.className = 'bo-aviso'; escreve(p, t); av.appendChild(p) });
    el('bo-bio').hidden = !d.face;
    el('bo-exportar').disabled = !(m.fechada);
    mostrarMolde(!!d.molde);
    el('bo-exportar-molde').disabled = !(d.molde && d.molde.exportavel);
    escreve(el('bo-estado'), m.fechada ? '' : 'A malha não fechou: o STL não é exportado.');
    var vv = (d.molde && VISTA_ABERTURA[d.molde.abertura]) || VISTA[d.direcao] || VISTA.ant;
    BO.camB.yaw = vv[0]; BO.camB.pitch = vv[1];
    fetch('/api/bolus/volume?b=' + encodeURIComponent(b) + '&qual=bolus&r=' + d.r)
      .then(function(r){ return r.arrayBuffer() }).then(function(buf){
        if(BO.b !== b || BO.r !== d.r) return;
        BO.bolus = vol(d.previa, buf); desenharD(1); desenharE(1); PLANOS.forEach(carregarCorte);
      });
    if(d.molde) fetch('/api/bolus/volume?b=' + encodeURIComponent(b) + '&qual=molde&r=' + d.r)
      .then(function(r){ return r.arrayBuffer() }).then(function(buf){
        if(BO.b !== b || BO.r !== d.r) return;
        BO.molde = vol(d.molde.previa, buf); desenharD(1);
      });
  }).catch(function(e){ apaga(); bt.disabled = false; BO.gerando = false; liberarAbrir(); escreve(el('bo-estado'), String(e)) });
};

function abrirAto(peca){
  if(!BO.res || BO.velho || BO.res.peca === 'aplicador') return;
  if(peca === 'molde' && !(BO.res.molde && BO.res.molde.exportavel)) return;
  BO.peca = peca;
  el('bo-exp-p-bolus').hidden = (peca !== 'bolus'); el('bo-exp-p-molde').hidden = (peca !== 'molde');
  el('bo-ato').checked = false; el('bo-exp-ok').disabled = true;
  el('bo-bio2').hidden = !BO.res.face;
  el('bo-veu').hidden = false; el('bo-ato').focus();
}
el('bo-exportar').onclick = function(){ abrirAto('bolus') };
el('bo-exportar-molde').onclick = function(){ abrirAto('molde') };
el('bo-ato').onchange = function(){ el('bo-exp-ok').disabled = !this.checked };
el('bo-exp-nao').onclick = function(){ el('bo-veu').hidden = true; el('bo-ato').checked = false };
document.addEventListener('keydown', function(ev){ if(ev.key === 'Escape' && !el('bo-veu').hidden) el('bo-exp-nao').onclick() });
el('bo-exp-ok').onclick = function(){
  if(!el('bo-ato').checked) return;
  var bt = el('bo-exp-ok'); bt.disabled = true;
  fetch('/api/bolus/stl', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({b: BO.b, r: BO.r, declaro: true, frase: FRASE, peca: BO.peca})}).then(function(r){
      if(!r.ok) return r.json().then(function(j){ throw new Error(j.erro || ('HTTP ' + r.status)) });
      var nome = r.headers.get('X-Radai-Nome') || 'bolus.stl';
      return r.blob().then(function(b){
        var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = nome;
        document.body.appendChild(a); a.click(); setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove() }, 4000);
        escreve(el('bo-estado'), nome);
      });
    }).catch(function(e){ escreve(el('bo-estado'), String(e.message || e)) }).then(function(){
      el('bo-ato').checked = false; el('bo-veu').hidden = true;
    });
};

var AP = @AP_JS@;
function brilho(texto){
  var alvo = el('bo-c3b').parentNode;
  if(window.uiCarregando) window.uiCarregando(alvo, true, texto);
  return function(){ if(window.uiCarregando) window.uiCarregando(alvo, false) };
}
var CAMPO_AP = {canal_mm: 'bo-ap-canal', espacamento_mm: 'bo-ap-esp', distancia_mm: 'bo-ap-dist',
  corpo_mm: 'bo-ap-corpo', diametro_externo_mm: 'bo-ap-od', raio: 'bo-ap-raio',
  raio_padrao_mm: 'bo-ap-raio', eixo: 'bo-ap-eixo'};
function tremerCampo(campo){
  var e = el(CAMPO_AP[campo] || ''); if(!e || !window.uiTremer) return;
  window.uiTremer(e.closest('.g') || e);
}
function pecaAtual(){ var r = document.querySelector('input[name=bo-peca]:checked'); return r ? r.value : 'bolus' }
function mostrarPeca(){
  var ap = pecaAtual() === 'aplicador';
  el('bo-ctl-bolus').hidden = ap; el('bo-pecas').hidden = ap;
  el('bo-ctl-ap').hidden = !ap; el('bo-ap-pecas').hidden = !ap;
  limparResultado();
  if(BO.meta){ desenharE(1); PLANOS.forEach(carregarCorte) }
}
[].forEach.call(document.querySelectorAll('input[name=bo-peca]'), function(r){ r.addEventListener('change', mostrarPeca) });
function apPisos(){
  var a = AP.afterloaders[el('bo-ap-afterloader').value], c = AP.cateteres[el('bo-ap-cateter').value] || {};
  var piso = Math.max(a == null ? 17 : a, c.piso == null ? AP.padrao : c.piso);
  var minimo = Math.max(piso, AP.padrao);
  el('bo-ap-raio').min = minimo;
  escreve(el('bo-ap-piso'), 'piso %s mm · padrão a partir de %s mm'.replace('%s', piso).replace('%s', minimo));
}
el('bo-ap-cateter').addEventListener('change', function(){
  var c = AP.cateteres[this.value] || {};
  el('bo-ap-od-l').hidden = (c.od != null);
  var od = (c.od != null) ? c.od : +el('bo-ap-od').value;
  el('bo-ap-canal').value = (od + AP.folga).toFixed(1);
  apPisos();
});
el('bo-ap-od').addEventListener('change', function(){ el('bo-ap-canal').value = (+this.value + AP.folga).toFixed(1) });
el('bo-ap-afterloader').addEventListener('change', apPisos);
apPisos();
['bo-ap-afterloader', 'bo-ap-cateter', 'bo-ap-od', 'bo-ap-raio', 'bo-ap-canal', 'bo-ap-dist', 'bo-ap-esp', 'bo-ap-corpo',
 'bo-ap-dir', 'bo-ap-eixo', 'bo-ap-trajeto', 'bo-ap-entrada', 'bo-ap-funil'].forEach(function(i){ el(i).addEventListener('change', marcarVelho) });
function parametrosAp(){
  return {b: BO.b, caixa: BO.caixa, direcao: el('bo-ap-dir').value, eixo: el('bo-ap-eixo').value,
    afterloader: el('bo-ap-afterloader').value, cateter: el('bo-ap-cateter').value,
    diametro_externo_mm: +el('bo-ap-od').value, raio_padrao_mm: +el('bo-ap-raio').value,
    canal_mm: +el('bo-ap-canal').value,
    distancia_mm: +el('bo-ap-dist').value, espacamento_mm: +el('bo-ap-esp').value,
    corpo_mm: +el('bo-ap-corpo').value, trajeto: el('bo-ap-trajeto').value,
    entrada: el('bo-ap-entrada').value, funil: el('bo-ap-funil').checked};
}
function raioTxt(v){ return (v == null || v >= AP.reto) ? 'reto' : num(v) + ' mm' }
function aviso(alvo, t, classe){ var p = document.createElement('div'); p.className = 'bo-aviso' + (classe ? ' ' + classe : ''); escreve(p, t); alvo.appendChild(p) }
function mostrarBloqueio(d){
  escreve(el('bo-estado'), (d.bloqueio && d.bloqueio.resumo) || d.erro);
  el('bo-estado').classList.add('erro');
  if(d.campo) tremerCampo(d.campo);
  var av = el('bo-avisos'); av.innerHTML = '';
  ((d.bloqueio || {}).propostas || []).forEach(function(t){ aviso(av, t, 'bo-bloq') });
  if((d.bloqueio || {}).caixa_sugerida) botaoDaSugerida(av, d.bloqueio.caixa_sugerida);
  if(window.radaiRetraduzir) window.radaiRetraduzir();
}
function botaoDaSugerida(alvo, sug){
  var b = document.createElement('button');
  b.type = 'button'; b.className = 'ui-bt bo-sugerida'; b.id = 'bo-ap-sugerida';
  escreve(b, 'Usar a caixa sugerida');
  b.onclick = function(){
    BO.caixa = {x0: +sug.x0, x1: +sug.x1, y0: +sug.y0, y1: +sug.y1, z0: +sug.z0, z1: +sug.z1};
    desenharCaixas(); desenharE(1);
    if(b.parentNode) b.parentNode.removeChild(b);
    el('bo-estado').classList.remove('erro');
    escreve(el('bo-estado'), 'A caixa mudou para a sugerida: confira se o alvo continua dentro e gere de novo.');
    if(window.radaiRetraduzir) window.radaiRetraduzir();
  };
  alvo.appendChild(b);
}
function mostrarAplicador(d, b){
  BO.res = d; BO.r = d.r; BO.velho = false; BO.molde = null;
  el('bo-resultado').classList.remove('bo-velho');
  var m = d.malha || {}, amarela = d.classe === 'amarelo';
  el('bo-tab').innerHTML =
    '<tr><td>' + 'curva' + '</td><td class="' + (amarela ? 'bo-amarela' : '') + '">' + (amarela ? 'amarela' : 'verde') + '</td></tr>' +
    linha('raio mínimo medido', raioTxt(d.raio_min_mm)) + linha('piso do equipamento', num(d.piso_mm, 0) + ' mm') +
    linha('raio padrão', num(d.padrao_mm, 0) + ' mm') + linha('face de entrada', d.face_entrada || '—') +
    linha('canais', (d.canais || []).length) +
    (d.canais || []).map(function(c){ return linha('canal ' + c.n, raioTxt(c.raio_min_mm) + ' · pele ' +
      num(c.pele_min_mm) + '–' + num(c.pele_max_mm) + ' mm · Ø ' + num(c.diametro_medido_mm, 2) + ' mm') }).join('') +
    linha('parede mínima', num(d.parede_min_mm) + ' mm') + linha('volume do material', num(d.volume_cm3) + ' cm³') +
    linha('dimensões', (d.dimensoes_mm || []).map(function(v){ return Math.round(v) }).join(' × ') + ' mm') +
    linha('malha fechada', m.fechada ? 'sim' : 'não') + linha('ida e volta STL → voxel (DSC)', num(d.dsc_ida_volta, 4)) +
    linha('triângulos', (m.triangulos || 0).toLocaleString()) + linha('peças', d.pecas) +
    linha('grade de trabalho', num(d.grade_mm, 2) + ' mm') + linha('tempo', num(d.tempo_s) + ' s');
  var av = el('bo-avisos'); av.innerHTML = '';
  (d.avisos || []).forEach(function(t){ aviso(av, t) });
  (d.exigencias || []).forEach(function(t){ aviso(av, t, 'bo-exig') });
  el('bo-bio').hidden = true;
  el('bo-ap-exportar').disabled = !d.exportavel;
  escreve(el('bo-estado'), d.exportavel ? '' : 'A malha não fechou: o STL não é exportado.');
  var vv = VISTA[d.direcao] || VISTA.ant;
  BO.camB.yaw = vv[0]; BO.camB.pitch = vv[1];
  fetch('/api/bolus/volume?b=' + encodeURIComponent(b) + '&qual=bolus&r=' + d.r)
    .then(function(r){ return r.arrayBuffer() }).then(function(buf){
      if(BO.b !== b || BO.r !== d.r) return;
      BO.bolus = vol(d.previa, buf); desenharD(1); desenharE(1); PLANOS.forEach(carregarCorte);
    });
}
el('bo-ap-gerar').onclick = function(){
  if(!BO.meta) return;
  var b = BO.b, bt = el('bo-ap-gerar'); bt.disabled = true;
  BO.gerando = true; el('bo-abrir').disabled = true;
  limparResultado();
  escreve(el('bo-estado'), 'gerando o aplicador…');
  var apaga = brilho('gerando o aplicador…');
  post('/api/bolus/aplicador/gerar', parametrosAp()).then(function(d){
    apaga(); bt.disabled = false; BO.gerando = false; liberarAbrir();
    if(BO.b !== b) return;
    if(d.erro){ mostrarBloqueio(d); return }
    mostrarAplicador(d, b);
  }).catch(function(e){ apaga(); bt.disabled = false; BO.gerando = false; liberarAbrir(); escreve(el('bo-estado'), String(e)) });
};
function liberarExpAp(){
  var curva = !!(BO.res && BO.res.classe === 'amarelo');
  el('bo-ap-exp-ok').disabled = !(el('bo-ap-ato').checked && (!curva || el('bo-ap-ato-curva').checked));
}
function linhaDupla(alvo, a, v){
  var tr = document.createElement('tr'), x = document.createElement('td'), y = document.createElement('td');
  escreve(x, a); escreve(y, v); tr.appendChild(x); tr.appendChild(y); alvo.appendChild(tr);
}
function abrirAtoAp(){
  if(!BO.res || BO.velho || BO.res.peca !== 'aplicador' || !BO.res.exportavel) return;
  var t = el('bo-ap-params'); t.innerHTML = '';
  (BO.res.parametros_tela || []).forEach(function(x){ linhaDupla(t, x[0], x[1]) });
  var al = el('bo-ap-alertas'); al.innerHTML = '';
  (BO.res.canais_tela || []).forEach(function(x){ aviso(al, x) });
  (BO.res.avisos || []).forEach(function(x){ aviso(al, x) });
  var ex = el('bo-ap-exig'); ex.innerHTML = '';
  (BO.res.exigencias || []).forEach(function(x){ aviso(ex, x, 'bo-exig') });
  el('bo-ap-curva-l').hidden = BO.res.classe !== 'amarelo';
  el('bo-ap-ato').checked = false; el('bo-ap-ato-curva').checked = false; liberarExpAp();
  el('bo-ap-veu').hidden = false; el('bo-ap-ato').focus();
}
el('bo-ap-exportar').onclick = abrirAtoAp;
el('bo-ap-ato').onchange = liberarExpAp;
el('bo-ap-ato-curva').onchange = liberarExpAp;
el('bo-ap-exp-nao').onclick = function(){ el('bo-ap-veu').hidden = true; el('bo-ap-ato').checked = false; el('bo-ap-ato-curva').checked = false };
document.addEventListener('keydown', function(ev){ if(ev.key === 'Escape' && !el('bo-ap-veu').hidden) el('bo-ap-exp-nao').onclick() });
el('bo-ap-exp-ok').onclick = function(){
  if(!el('bo-ap-ato').checked) return;
  var bt = el('bo-ap-exp-ok'); bt.disabled = true;
  fetch('/api/bolus/aplicador/exportar', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({b: BO.b, r: BO.r, declaro: true, frase: AP.frase,
      declaro_curva: el('bo-ap-ato-curva').checked, frase_curva: AP.frase_curva})}).then(function(r){
      if(!r.ok) return r.json().then(function(j){ throw new Error(j.erro || ('HTTP ' + r.status)) });
      var nome = r.headers.get('X-Radai-Nome') || 'aplicador.zip';
      return r.blob().then(function(b){
        var a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = nome;
        document.body.appendChild(a); a.click(); setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove() }, 4000);
        escreve(el('bo-estado'), nome);
      });
    }).catch(function(e){ escreve(el('bo-estado'), String(e.message || e)) }).then(function(){
      el('bo-ap-ato').checked = false; el('bo-ap-ato-curva').checked = false; el('bo-ap-veu').hidden = true;
    });
};
})();
"""

PAGINA = u"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gerar b&oacute;lus &middot; 3D Printed Bolus</title>
<style>@CSS@</style></head><body><div class="bo-wrap">

@CABECA@

@CARTAO@
<div class="bo-legenda" data-radai-frase>TC diagn&oacute;stica recente, sem
 m&aacute;scara: o b&oacute;lus &eacute; sobre a pele. RM &eacute; recusada.</div>
<div class="bo-msg" id="bo-msg"></div>
@ESCOLHA@

<div class="bo-corpo" id="bo-corpo" style="display:none">
 <div class="bo-esq">
  <div class="bo-rotlinha"><span class="bo-rot" data-radai-frase>paciente,
    caixa e b&oacute;lus</span>
   <span class="bo-vistas">
    <button type="button" class="bo-bt2" data-vista="ant"
     data-radai-frase>Anterior</button>
    <button type="button" class="bo-bt2" data-vista="post"
     data-radai-frase>Posterior</button>
    <button type="button" class="bo-bt2" data-vista="dir"
     data-radai-frase>Direita</button>
    <button type="button" class="bo-bt2" data-vista="esq"
     data-radai-frase>Esquerda</button></span></div>
  <div class="bo-palco3d"><canvas id="bo-c3d" role="img"
   aria-label="paciente, caixa e bólus em 3D; arraste para girar"></canvas>
   <div class="bo-dica" data-radai-frase>arraste para girar; a roda aproxima</div></div>
  <div class="bo-mprs">
   <div class="bo-mpr"><span class="bo-mpr-rot">axial</span>
    <div class="bo-mpr-cel"><div class="bo-mpr-palco" id="bo-p-ax">
     <img id="bo-i-ax" alt="" draggable="false">
     <svg id="bo-s-ax" preserveAspectRatio="none"></svg></div></div>
    <input type="range" id="bo-r-ax" aria-label="corte axial"></div>
   <div class="bo-mpr"><span class="bo-mpr-rot">coronal</span>
    <div class="bo-mpr-cel"><div class="bo-mpr-palco" id="bo-p-co">
     <img id="bo-i-co" alt="" draggable="false">
     <svg id="bo-s-co" preserveAspectRatio="none"></svg></div></div>
    <input type="range" id="bo-r-co" aria-label="corte coronal"></div>
   <div class="bo-mpr"><span class="bo-mpr-rot">sagital</span>
    <div class="bo-mpr-cel"><div class="bo-mpr-palco" id="bo-p-sa">
     <img id="bo-i-sa" alt="" draggable="false">
     <svg id="bo-s-sa" preserveAspectRatio="none"></svg></div></div>
    <input type="range" id="bo-r-sa" aria-label="corte sagital"></div>
  </div>
  <div class="bo-janelas">
   <span class="bo-rot" data-radai-frase>janela</span>
   <button type="button" class="bo-bt2 on" data-jan="pele"
    data-radai-frase>pele</button>
   <button type="button" class="bo-bt2" data-jan="partes_moles"
    data-radai-frase>partes moles</button>
   <button type="button" class="bo-bt2" data-jan="osso"
    data-radai-frase>osso</button>
   <span class="bo-info"><span data-radai-frase>caixa</span>
    <b id="bo-caixa-mm">&mdash;</b></span>
  </div>
  <div class="bo-legenda" data-radai-frase>Arraste as bordas da caixa em
   qualquer um dos tr&ecirc;s planos; arrastar por dentro move a caixa.</div>
 </div>

 <div class="bo-dir">
  <div class="bo-rotlinha">
   <span class="bo-rot" id="bo-rot-b" data-radai-frase>s&oacute; o
    b&oacute;lus</span>
   <span class="bo-seg" id="bo-ver" hidden>
    <button type="button" class="bo-bt2" data-ver="bolus" aria-pressed="false"
     data-radai-frase>s&oacute; o b&oacute;lus</button>
    <button type="button" class="bo-bt2" data-ver="molde" aria-pressed="false"
     data-radai-frase>s&oacute; o molde</button>
    <button type="button" class="bo-bt2 on" data-ver="ambos" aria-pressed="true"
     data-radai-frase>b&oacute;lus e molde</button></span></div>
  <div class="bo-palco3d b"><canvas id="bo-c3b" role="img"
   aria-label="o resultado em 3D: o bólus e, se pedido, o molde; arraste para girar"></canvas>
   <div class="bo-dica" data-radai-frase>arraste para girar; a roda aproxima</div></div>

  <div class="bo-peca-esc" role="radiogroup" aria-label="peça">
   <label><input type="radio" name="bo-peca" value="bolus" checked>
    <span data-radai-frase>B&oacute;lus</span></label>
   <label><input type="radio" name="bo-peca" value="aplicador">
    <span data-radai-frase>Aplicador de braquiterapia (superf&iacute;cie)</span></label>
   @AJ_APLICADOR@</div>

  <div class="bo-ctl" id="bo-ctl-bolus">
   <div class="g"><span data-radai-frase>Modo</span>
    <label><input type="radio" name="bo-modo" value="anatomico" checked>
     <span data-radai-frase>Anat&ocirc;mico</span></label>
    <label><input type="radio" name="bo-modo" value="caixa">
     <span data-radai-frase>Caixa</span></label></div>
   <div class="g"><label class="g-rot" for="bo-esp" data-radai-frase>Espessura (mm)</label>
    <input type="number" id="bo-esp" min="@EMIN@" max="@EMAX@" step="1"
     value="@EPAD@" inputmode="numeric"></div>
   <div class="bo-legenda" id="bo-esp-caixa" hidden data-radai-frase>No modo
    Caixa a espessura &eacute; a da pr&oacute;pria caixa: afaste a face externa
    para engrossar.</div>
   <div class="g"><label class="g-rot" for="bo-suav" data-radai-frase>Suaviza&ccedil;&atilde;o (mm)</label>
    <input type="range" id="bo-suav" min="0" max="@SMAX@" step="0.5"
     value="1"><span id="bo-suav-v"></span></div>
   <div class="g"><label class="g-rot" for="bo-dir" data-radai-frase>Dire&ccedil;&atilde;o de
     coloca&ccedil;&atilde;o</label>
    <select id="bo-dir">
     <option value="auto" data-radai-frase>autom&aacute;tica</option>
     <option value="ant" data-radai-frase>anterior</option>
     <option value="post" data-radai-frase>posterior</option>
     <option value="dir" data-radai-frase>direita</option>
     <option value="esq" data-radai-frase>esquerda</option>
     <option value="sup" data-radai-frase>superior</option>
     <option value="inf" data-radai-frase>inferior</option>
    </select></div>
   <label class="g"><input type="checkbox" id="bo-marcas" checked>
    <span data-radai-frase>Marcas de lado em relevo (letra, seta e
     entalhe)</span></label>
   <label class="g"><input type="checkbox" id="bo-molde">
    <span data-radai-frase>Molde: casca oca para encher de cera</span></label>
   <div class="bo-molde" id="bo-molde-ctl" hidden>
    <div class="g"><label class="g-rot" for="bo-casca" data-radai-frase>Casca do molde (mm)</label>
     <input type="number" id="bo-casca" min="@CMIN@" max="@CMAX@" step="1"
      value="@CPAD@" inputmode="numeric"></div>
    <div class="g"><label class="g-rot" for="bo-abertura" data-radai-frase>Abertura</label>
     <select id="bo-abertura">@ABERTURAS@</select></div>
    <div class="bo-legenda" data-radai-frase>O interior do molde &eacute; o
     pr&oacute;prio b&oacute;lus, tri&acirc;ngulo a tri&acirc;ngulo. Nas
     laterais a face do b&oacute;lus &eacute; plana (o corte da caixa): a
     cera derramada at&eacute; a borda a reproduz. A face externa segue a
     pele, e a cera assenta plana.</div>
   </div>
   <div class="bo-legenda" data-radai-frase>O b&oacute;lus s&oacute; ocupa o
    ar que est&aacute; &agrave; frente da pele na dire&ccedil;&atilde;o de
    coloca&ccedil;&atilde;o: ele entra e sai sem reentr&acirc;ncia, e
    cavidade interna nunca vira b&oacute;lus. S&oacute; a face externa
    &eacute; suavizada.</div>
  </div>

@PAINEL_AP@

  <div class="bo-pecas" id="bo-pecas"><button id="bo-gerar" class="bo-bt ui-verde"
    type="button" data-radai-frase>Gerar b&oacute;lus</button><button id="bo-exportar"
    class="bo-bt2" type="button" disabled data-radai-frase>Exportar STL do
    b&oacute;lus</button><button id="bo-exportar-molde" class="bo-bt2" type="button"
    disabled data-radai-frase>Exportar STL do molde</button></div>
  <div class="bo-pecas" id="bo-ap-pecas" hidden><button id="bo-ap-gerar"
    class="bo-bt ui-verde" type="button" data-radai-frase>Gerar aplicador</button><button
    id="bo-ap-exportar" class="bo-bt2" type="button" disabled
    data-radai-frase>Exportar STL do aplicador</button></div>
  <div class="bo-msg" id="bo-estado" role="status"></div>
  <div id="bo-resultado">
   <table class="bo-tab"><tbody id="bo-tab"></tbody></table>
  </div>
  <div class="bo-avisos" id="bo-avisos"></div>
  <div class="bo-aviso bo-bio" id="bo-bio" hidden><span
    data-radai-frase>@BIOMETRIA@</span></div>
 </div>
</div>

@ALERTA_PE@

<div class="bo-veu" id="bo-veu" hidden>
 <div class="bo-janela" role="dialog" aria-modal="true"
  aria-labelledby="bo-exp-t">
  <h2 id="bo-exp-t" data-radai-frase>Exportar STL &mdash; ato declarado</h2>
  <p data-radai-frase>@ALERTA@</p>
  <p data-radai-frase>Este arquivo n&atilde;o carrega a
   aprova&ccedil;&atilde;o de ningu&eacute;m. A declara&ccedil;&atilde;o abaixo
   vale para esta exporta&ccedil;&atilde;o s&oacute;, e n&atilde;o fica
   lembrada.</p>
  <p id="bo-bio2" hidden><span data-radai-frase>@BIOMETRIA@</span></p>
  <p id="bo-exp-p-bolus" data-radai-frase>Pe&ccedil;a: o b&oacute;lus.</p>
  <p id="bo-exp-p-molde" hidden data-radai-frase>Pe&ccedil;a: o molde
   &mdash; a casca oca, com o interior igual ao b&oacute;lus.</p>
  <label class="bo-ato"><input type="checkbox" id="bo-ato">
   <span id="bo-frase-ato" data-radai-frase>@FRASE@</span></label>
  <div class="bo-acoes">
   <button type="button" class="bo-bt2" id="bo-exp-nao"
    data-radai-frase>Cancelar</button>
   <button type="button" class="bo-bt ui-verde" id="bo-exp-ok" disabled
    data-radai-frase>Exportar</button>
  </div>
 </div>
</div>

<div class="bo-veu" id="bo-ap-veu" hidden>
 <div class="bo-janela" role="dialog" aria-modal="true"
  aria-labelledby="bo-ap-exp-t">
  <h2 id="bo-ap-exp-t" data-radai-frase>Exportar STL do aplicador &mdash; ato
   declarado</h2>
  <p data-radai-frase>@ALERTA_AP@</p>
  <p data-radai-frase>Sai um .zip com o STL e a ficha: todos os
   par&acirc;metros, os canais medidos e os avisos que n&atilde;o somem. A
   declara&ccedil;&atilde;o abaixo vale para esta exporta&ccedil;&atilde;o
   s&oacute;.</p>
  <table class="bo-tab"><tbody id="bo-ap-params"></tbody></table>
  <div class="bo-avisos" id="bo-ap-alertas"></div>
  <div class="bo-avisos" id="bo-ap-exig"></div>
  <label class="bo-ato"><input type="checkbox" id="bo-ap-ato">
   <span data-radai-frase>@FRASE_AP@</span></label>
  <label class="bo-ato" id="bo-ap-curva-l" hidden><input type="checkbox"
   id="bo-ap-ato-curva"><span data-radai-frase>@FRASE_CURVA@</span></label>
  <div class="bo-acoes">
   <button type="button" class="bo-bt2" id="bo-ap-exp-nao"
    data-radai-frase>Cancelar</button>
   <button type="button" class="bo-bt ui-verde" id="bo-ap-exp-ok" disabled
    data-radai-frase>Exportar</button>
  </div>
 </div>
</div>

</div>
<script>@JS@</script>
</body></html>"""


ROTULO_DA_ABERTURA = {
    "externa": u"externa (face oposta &agrave; pele)",
    "superior": u"superior", "inferior": u"inferior",
    "esquerda": u"esquerda", "direita": u"direita"}


def _opcoes_de_abertura():
    return u"".join(
        u'<option value="%s"%s data-radai-frase>%s</option>'
        % (a, u" selected" if a == radai_bolus.ABERTURA_PADRAO else u"",
           ROTULO_DA_ABERTURA[a]) for a in radai_bolus.ABERTURAS)


ICONE_DO_MODULO = u"camadas"


def _cabeca():
    import radai_ui
    ajuda = radai_ui.ajuda(
        u"<b>Inova&ccedil;&atilde;o, n&atilde;o produ&ccedil;&atilde;o.</b>",
        u"<b>O que sai daqui, e o que n&atilde;o sai.</b>",
        u"Sai um STL, por ato declarado a cada exporta&ccedil;&atilde;o, em "
        u"mil&iacute;metros e no sistema de coordenadas do paciente (LPS). "
        u"N&atilde;o sai RTSTRUCT: para o plano considerar o b&oacute;lus, o "
        u"f&iacute;sico faz uma TC com ele posto. O arquivo n&atilde;o leva "
        u"nome, registro nem data, e o cabe&ccedil;alho diz que &eacute; "
        u"rascunho n&atilde;o aprovado.",
        u"O aplicador de braquiterapia sai num .zip, com o STL e a ficha "
        u"de todos os par&acirc;metros e avisos.")
    return radai_ui.cabeca_de_funcao(
        ICONE_DO_MODULO, u"Gerar bólus",
        u"a caixa no MPR, a camada sobre a pele, e o STL para imprimir",
        ajuda, u"bolus")


def _esc(t):
    return (str(t if t is not None else u"").replace(u"&", u"&amp;")
            .replace(u"<", u"&lt;").replace(u">", u"&gt;")
            .replace(u'"', u"&quot;"))


def _aj(chave):
    import radai_bolus_aplicador as A
    import radai_ui
    return radai_ui.ajuda(*[_esc(p) for p in A.AJUDA[chave]], direita=True)


def _opcoes(itens, escolhido):
    return u"".join(
        u'<option value="%s"%s>%s</option>'
        % (_esc(v), u" selected" if v == escolhido else u"", _esc(r))
        for v, r in itens)


def _campo(ident, rotulo, controle, ajuda=u"", oculto=False):
    return (u'<div class="g"%s%s><label class="g-rot" for="%s" '
            u'data-radai-frase>%s</label>%s%s</div>'
            % (u' id="%s-l"' % ident if oculto else u"",
               u" hidden" if oculto else u"", ident, _esc(rotulo), controle,
               ajuda))


def _numero(ident, chave, valor, passo):
    import radai_bolus_aplicador as A
    lo, hi = A.FAIXAS[chave]
    return (u'<input type="number" id="%s" min="%s" max="%s" step="%s" '
            u'value="%s" inputmode="decimal">' % (ident, lo, hi, passo, valor))


def opcao_do_menu(item):
    return u"%s — %d mm (%s)" % (item["nome"], int(item["piso_mm"]),
                                 item["curta"])


def painel_do_aplicador():
    import radai_bolus_aplicador as A
    p = A.padroes()
    al = [(a["chave"], opcao_do_menu(a)) for a in A.AFTERLOADERS]
    ca = [(c["chave"], opcao_do_menu(c)) for c in A.CATETERES]
    direcoes = [("auto", u"automática")] + [
        (d, A.DIRECAO_POR_EXTENSO[d]) for d in ("ant", "post", "dir", "esq",
                                                "sup", "inf")]
    eixos = [(e[0], e[2]) for e in A.EIXOS]
    trajetos = [("aberto", u"aberto: ponta e conector saem do corpo"),
                ("cego", u"fundo cego")]
    entradas = [("inicio", u"início do eixo (direita, anterior ou inferior)"),
                ("fim", u"fim do eixo (esquerda, posterior ou superior)")]
    hu = int(radai_bolus.LIMIAR_HU)
    linhas = [
        u'<div class="bo-alerta bo-ap-alerta"><span data-radai-frase>%s'
        u'</span></div>' % _esc(A.ALERTA),
        _campo(u"bo-ap-afterloader", u"Afterloader",
               u'<select id="bo-ap-afterloader">%s</select>'
               % _opcoes(al, p["afterloader"]), _aj("afterloader")),
        _campo(u"bo-ap-cateter", u"Cateter",
               u'<select id="bo-ap-cateter">%s</select>'
               % _opcoes(ca, p["cateter"]), _aj("cateter")),
        _campo(u"bo-ap-od", u"Diâmetro externo do cateter (mm)",
               _numero(u"bo-ap-od", "diametro_externo_mm",
                       p["diametro_externo_mm"], u"0.1"), _aj("od"),
               oculto=True),
        _campo(u"bo-ap-raio", u"Raio padrão do canal (mm)",
               _numero(u"bo-ap-raio", "raio_padrao_mm", p["raio_padrao_mm"],
                       u"1") + _aj("raio"),
               u'<span class="bo-info" id="bo-ap-piso"></span>'),
        _campo(u"bo-ap-canal", u"Diâmetro do canal (mm)",
               _numero(u"bo-ap-canal", "canal_mm", p["canal_mm"], u"0.1"),
               _aj("canal")),
        _campo(u"bo-ap-dist", u"Eixo do canal até a pele (mm)",
               _numero(u"bo-ap-dist", "distancia_mm", p["distancia_mm"],
                       u"0.5"), _aj("distancia")),
        _campo(u"bo-ap-esp", u"Espaçamento entre canais (mm)",
               _numero(u"bo-ap-esp", "espacamento_mm", p["espacamento_mm"],
                       u"0.5"), _aj("espacamento")),
        _campo(u"bo-ap-corpo", u"Espessura do corpo (mm)",
               _numero(u"bo-ap-corpo", "corpo_mm", p["corpo_mm"], u"0.5"),
               _aj("corpo")),
        _campo(u"bo-ap-dir", u"Direção de colocação",
               u'<select id="bo-ap-dir">%s</select>'
               % _opcoes(direcoes, p["direcao"]), _aj("direcao")),
        _campo(u"bo-ap-eixo", u"Direção dos canais",
               u'<select id="bo-ap-eixo">%s</select>'
               % _opcoes(eixos, p["eixo"]), _aj("eixo")),
        _campo(u"bo-ap-trajeto", u"Trajeto",
               u'<select id="bo-ap-trajeto">%s</select>'
               % _opcoes(trajetos, p["trajeto"]), _aj("trajeto")),
        _campo(u"bo-ap-entrada", u"Face de entrada do cateter",
               u'<select id="bo-ap-entrada">%s</select>'
               % _opcoes(entradas, p["entrada"]), _aj("entrada")),
        u'<div class="g"><label class="bo-ap-ck"><input type="checkbox" '
        u'id="bo-ap-funil"%s> <span data-radai-frase>Entrada afunilada</span>'
        u'</label>%s</div>'
        % (u" checked" if p["funil"] else u"", _aj("funil")),
        u'<div class="g"><span class="g-rot" data-radai-frase>Superfície da '
        u'pele</span><span class="bo-info" data-radai-frase>limiar fixo de '
        u'%d HU</span>%s</div>' % (hu, _aj("superficie")),
        u'<div class="g"><span class="g-rot" data-radai-frase>Material'
        u'</span><span class="bo-info" data-radai-frase>PLA ou ABS, com o '
        u'mesmo preenchimento do controle de qualidade</span>%s</div>'
        % _aj("material"),
    ]
    return (u'<div class="bo-ctl" id="bo-ctl-ap" hidden>%s</div>'
            % u"\n".join(linhas))


def dados_do_aplicador_para_o_js():
    import json
    import radai_bolus_aplicador as A
    d = {"frase": A.FRASE_DO_ATO, "frase_curva": A.FRASE_DA_CURVA,
         "padrao": int(A.RAIO_PADRAO_MM), "folga": A.FOLGA_PADRAO_MM,
         "reto": A.RAIO_RETO_MM,
         "afterloaders": dict((a["chave"], int(a["piso_mm"]))
                              for a in A.AFTERLOADERS),
         "cateteres": dict((c["chave"], {"piso": int(c["piso_mm"]),
                                         "od": c["diametro_mm"]})
                           for c in A.CATETERES)}
    return json.dumps(d).replace(u"</", u"<\\/")


def _alerta():
    import radai_ui
    return radai_ui.alerta(radai_bolus.ALERTA)


def pagina():
    import json
    import radai_bolus_aplicador as A
    import radai_ui
    return (PAGINA.replace("@CSS@", CSS)
                  .replace("@CARTAO@", radai_ui.cartao_de_serie(
                      u"bo-cartao", u"bo_escolha", u"Escolha a série",
                      chave_modulo=u"bolus"))
                  .replace("@ESCOLHA@", _escolha())
                  .replace("@ICO_PASTA@", radai_ui.icone(u"pasta"))
                  .replace("@JS@", JS.replace(
                      "@FRASE_JS@", json.dumps(radai_bolus.FRASE_DO_ATO))
                      .replace("@SETA_JS@", json.dumps(
                          radai_ui.icone(u"acima")).replace(u"</", u"<\\/"))
                      .replace("@AP_JS@", dados_do_aplicador_para_o_js())
                      .replace("@USO_JS@", json.dumps(USO_DA_VARREDURA)))
                  .replace("@AJ_APLICADOR@", _aj("aplicador"))
                  .replace("@PAINEL_AP@", painel_do_aplicador())
                  .replace("@ALERTA_AP@", _esc(A.ALERTA))
                  .replace("@FRASE_AP@", _esc(A.FRASE_DO_ATO))
                  .replace("@FRASE_CURVA@", _esc(A.FRASE_DA_CURVA))
                  .replace("@CABECA@", _cabeca())
                  .replace("@ALERTA_PE@", _alerta())
                  .replace("@ALERTA@", radai_bolus.ALERTA)
                  .replace("@BIOMETRIA@", radai_bolus.AVISO_BIOMETRIA)
                  .replace("@FRASE@", radai_bolus.FRASE_DO_ATO)
                  .replace("@EMIN@", str(radai_bolus.ESPESSURA_MIN_MM))
                  .replace("@EMAX@", str(radai_bolus.ESPESSURA_MAX_MM))
                  .replace("@EPAD@", str(radai_bolus.ESPESSURA_PADRAO_MM))
                  .replace("@CMIN@", str(radai_bolus.CASCA_MIN_MM))
                  .replace("@CMAX@", str(radai_bolus.CASCA_MAX_MM))
                  .replace("@CPAD@", str(radai_bolus.CASCA_PADRAO_MM))
                  .replace("@ABERTURAS@", _opcoes_de_abertura())
                  .replace("@SMAX@", str(int(radai_bolus.SUAVIZACAO_MAX_MM))))


PASTA_HTML = u"""<div class="bo-linha">
 <div class="bo-campo" style="flex:2"><label for="bo-pasta"
   data-radai-frase>Pasta da tomografia</label>
  <div class="bo-campo-l"><input id="bo-pasta" type="text" autocomplete="off"
   spellcheck="false">@FAV@</div></div>
 <button id="bo-procurar" class="ui-bt" type="button">@ICO_PASTA@<span
  data-radai-frase>Procurar&hellip;</span></button>
 <button id="bo-listar" class="bo-bt2" type="button"
  data-radai-frase>Procurar s&eacute;ries</button>
</div>
<div class="bo-filtro">@FILTRO@</div>
<div class="ui-vl-est" id="bo-busca" role="status" aria-live="polite"></div>
<div class="bo-linha">
 <div class="bo-campo" style="flex:3"><label for="bo-serie"
   data-radai-frase>S&eacute;rie</label><div class="bo-serie-l"><select
   id="bo-serie"></select></div></div>
 <button id="bo-abrir" class="bo-bt ui-verde" type="button" disabled
  data-radai-frase>Abrir</button>
</div>"""


def _escolha():
    import radai_tabela_acervo
    import radai_ui
    pasta = (PASTA_HTML.replace(u"@FAV@", radai_ui.botao_favorita(u"bo-pasta"))
             .replace(u"@FILTRO@", radai_ui.filtro_de_data(u"bo_dias")))
    abas = radai_ui.abas_de_serie(
        u"bo_origem",
        [(u"acervo", u"Acervo local", radai_tabela_acervo.html(u"bo_acervo")),
         (u"pasta", u"Aponte uma pasta", pasta)],
        padrao=u"pasta", cor_var=u"--mod-bolus")
    return radai_ui.popup_de_serie(
        u"bo_escolha",
        abas + u'<div class="bo-msg" id="bo-msg-ps" role="status"></div>',
        sozinho=True)


def _meta(serie):
    pv = serie.previa or {}
    return {"forma": list(serie.forma), "esp": [float(v) for v in serie.esp],
            "extensao": [float(v) for v in serie.extensao],
            "caixa": radai_bolus.caixa_inicial(serie),
            "previa": {"forma": pv.get("forma"), "sp": pv.get("sp"),
                       "off": pv.get("off")},
            "sem_mesa": bool(pv.get("sem_mesa"))}


def _voxels_pelo_cabecalho(pasta, uid):
    try:
        import SimpleITK as sitk
        import engine
        # GUARDA: a varredura grava a pasta com o prefixo de caminho longo, que o GDCM não lista.
        pasta = engine._pasta_para_o_gdcm(pasta)
        if not pasta:
            return None
        if uid:
            n = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(pasta),
                                                              str(uid))
        else:
            n = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(str(pasta))
        if not n:
            return None
        r = sitk.ImageFileReader()
        r.SetFileName(n[0])
        r.ReadImageInformation()
        t = r.GetSize()
        quadros = t[2] if len(t) > 2 else 1
        return int(t[0]) * int(t[1]) * int(quadros) * len(n)
    except Exception:
        return None


def montar(app, registrar=None):
    from fastapi import Request
    from fastapi.responses import HTMLResponse, JSONResponse, Response

    @app.get("/bolus/gerar", response_class=HTMLResponse)
    def _tela():
        return radai_menu.aplicar(pagina(), "bolus_gerar")

    registrar_varredura()

    @app.post("/api/bolus/acervo")
    async def _do_acervo(request: Request):
        try:
            c = await request.json() or {}
            return await radai_web.no_threadpool(
                serie_do_acervo, str(c.get("bilhete") or ""))
        except Exception as e:
            return {"erro": u"%s: %s" % (type(e).__name__, str(e)[:200])}

    def _abrir(b):
        import engine
        s = _L.get(b)
        if s is None:
            raise radai_bolus.Recusa(u"Bilhete vencido — o programa foi "
                                     u"reiniciado desde a lista. Procure as "
                                     u"séries de novo.")
        radai_bolus.conferir_modalidade(s.get("modalidade"))
        import radai_batch
        real, erro = radai_batch.resolver_pasta(s)
        if erro or not real:
            raise radai_bolus.Recusa(u"Não consegui abrir a série: %s"
                                     % (erro or u"pasta sumiu"))
        if (int(s.get("cortes") or 0) * 512 * 512
                > radai_bolus.TETO_SERIE_VOXELS):
            radai_bolus.conferir_tamanho_da_serie(
                _voxels_pelo_cabecalho(real, s.get("uid")))
        with _TRAVA:
            _esquecer()
            uid = s.get("uid")
            serie = radai_bolus.abrir(lambda: engine.load_sitk(real, uid),
                                      s.get("modalidade"))
            _S.update({"b": b, "serie": serie, "visto": time.time()})
            _armar(SOLTAR_APOS_S)
        return _meta(serie)

    @app.post("/api/bolus/abrir")
    async def _abrir_rota(request: Request):
        try:
            c = await request.json() or {}
            b = str(c.get("b") or "")
            return JSONResponse(await radai_web.no_threadpool(_abrir, b))
        except radai_bolus.Recusa as e:
            return JSONResponse({"erro": str(e)})
        except Exception as e:
            return JSONResponse({"erro": u"%s: %s" % (type(e).__name__,
                                                      str(e)[:200])})

    @app.get("/api/bolus/volume")
    def _volume(b: str = "", qual: str = "corpo", r: str = ""):
        serie = _serie(b)
        if serie is None:
            return Response(status_code=404)
        if qual == "corpo":
            dados = serie.previa["densidade"].tobytes()
        else:
            if not r or _S.get("r") != r or _S.get("res") is None:
                return Response(status_code=404)
            if qual == "molde":
                mo = _S["res"].get("molde")
                if not mo:
                    return Response(status_code=404)
                dados = mo["previa"]["densidade"].tobytes()
            else:
                dados = _S["res"]["previa"]["densidade"].tobytes()
        return Response(content=dados, media_type="application/octet-stream",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/bolus/corte")
    def _corte(b: str = "", plano: str = "ax", i: int = 0, jan: str = "pele",
               r: str = ""):
        serie = _serie(b)
        if serie is None or plano not in radai_bolus.PLANOS:
            return Response(status_code=404)
        res = _S.get("res") if (r and _S.get("r") == r) else None
        try:
            png = radai_bolus.corte_png(serie, plano, i, jan, res)
        except Exception as e:
            return JSONResponse({"erro": u"%s: %s" % (type(e).__name__, e)},
                                status_code=500)
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    def _gerar(c):
        b = str(c.get("b") or "")
        serie = _serie(b)
        if serie is None:
            raise radai_bolus.Recusa(u"A série não está mais aberta — ela sai "
                                     u"da memória depois de dez minutos sem "
                                     u"uso. Abra de novo.")
        if not _TRAVA_GERAR.acquire(blocking=False):
            raise radai_bolus.Recusa(u"Já há um bólus sendo gerado. Espere ele "
                                     u"terminar.")
        try:
            res = radai_bolus.gerar(
                serie, c.get("caixa") or {}, str(c.get("modo") or "anatomico"),
                c.get("espessura", radai_bolus.ESPESSURA_PADRAO_MM),
                float(c.get("suavizacao") or 0.0),
                str(c.get("direcao") or "auto"), bool(c.get("marcas", True)),
                molde=c.get("molde") is True,
                casca_mm=c.get("casca", radai_bolus.CASCA_PADRAO_MM),
                abertura=str(c.get("abertura")
                             or radai_bolus.ABERTURA_PADRAO))
        finally:
            _TRAVA_GERAR.release()
        rid = _publicar(b, serie, res)
        fora = radai_bolus.resumo(res)
        fora["r"] = rid
        return fora

    @app.post("/api/bolus/gerar")
    async def _gerar_rota(request: Request):
        try:
            c = await request.json() or {}
            return JSONResponse(await radai_web.no_threadpool(_gerar, c))
        except radai_bolus.Recusa as e:
            return JSONResponse({"erro": str(e)})
        except Exception as e:
            return JSONResponse({"erro": u"%s: %s" % (type(e).__name__,
                                                      str(e)[:200])})

    @app.post("/api/bolus/stl")
    async def _stl(request: Request):
        try:
            c = await request.json() or {}
        except Exception:
            c = {}
        try:
            radai_bolus.conferir_ato(c.get("declaro"), c.get("frase"))
        except radai_bolus.Recusa as e:
            return JSONResponse({"erro": str(e)}, status_code=409)
        r = str(c.get("r") or "")
        with _TRAVA:
            res = _S.get("res") if (r and _S.get("r") == r
                                    and _S.get("b") == str(c.get("b") or "")) \
                else None
        if res is None:
            return JSONResponse({"erro": u"Este bólus não está mais na "
                                         u"memória. Gere de novo."},
                                status_code=404)
        if res.get("peca") == "aplicador":
            return JSONResponse({"erro": u"Este resultado é um aplicador: "
                                         u"ele sai pela exportação do "
                                         u"aplicador, com a ficha."},
                                status_code=409)
        peca = str(c.get("peca") or "bolus")
        if peca not in ("bolus", "molde"):
            return JSONResponse({"erro": u"Peça desconhecida: %s." % peca[:40]},
                                status_code=409)
        if peca == "molde":
            mo = res.get("molde")
            if not mo:
                return JSONResponse({"erro": u"Este bólus foi gerado sem "
                                             u"molde. Marque o molde e gere "
                                             u"de novo."}, status_code=404)
            if not mo["exportavel"]:
                return JSONResponse({"erro": u"O molde não é exportado: a "
                                             u"malha dele não fechou, ou a "
                                             u"abertura não achou face do "
                                             u"bólus."}, status_code=409)
            dados = mo["stl"]
            nome = radai_bolus.nome_do_molde(res, r)
            linha = radai_bolus.linha_do_ato_molde(res, nome)
        else:
            if not res["malha"]["fechada"]:
                return JSONResponse({"erro": u"A malha não fechou: o STL não "
                                             u"é exportado."}, status_code=409)
            dados = res["stl"]
            nome = radai_bolus.nome_do_stl(res, r)
            linha = radai_bolus.linha_do_ato(res, nome)
        try:
            _gravar_ato(linha)
        except Exception as e:
            return JSONResponse(
                {"erro": u"O ato não pôde ser registrado (%s: %s), e o STL "
                         u"não sai sem o registro." % (type(e).__name__,
                                                      str(e)[:160])},
                status_code=500)
        if registrar is not None:
            try:
                registrar(linha)
            except Exception:
                pass
        return Response(content=dados, media_type="model/stl",
                        headers={"Cache-Control": "no-store",
                                 "Content-Disposition":
                                     u'attachment; filename="%s"' % nome,
                                 "X-Radai-Nome": nome})

    def _gerar_ap(c):
        import radai_bolus_aplicador as A
        b = str(c.get("b") or "")
        serie = _serie(b)
        if serie is None:
            raise radai_bolus.Recusa(u"A série não está mais aberta — ela sai "
                                     u"da memória depois de dez minutos sem "
                                     u"uso. Abra de novo.")
        if not _TRAVA_GERAR.acquire(blocking=False):
            raise radai_bolus.Recusa(u"Já há uma peça sendo gerada. Espere "
                                     u"ela terminar.")
        try:
            res = A.gerar(serie, c.get("caixa") or {}, c)
        finally:
            _TRAVA_GERAR.release()
        rid = _publicar(b, serie, res)
        fora = A.resumo(res)
        fora["r"] = rid
        return fora

    @app.post("/api/bolus/aplicador/gerar")
    async def _gerar_ap_rota(request: Request):
        import radai_bolus_aplicador as A
        try:
            c = await request.json() or {}
            return JSONResponse(await radai_web.no_threadpool(_gerar_ap, c))
        except A.Bloqueio as e:
            return JSONResponse({"erro": str(e), "campo": e.campo,
                                 "bloqueio": A._json(e.detalhe)})
        except A.RecusaDoCampo as e:
            return JSONResponse({"erro": str(e), "campo": e.campo})
        except radai_bolus.Recusa as e:
            return JSONResponse({"erro": str(e)})
        except Exception as e:
            return JSONResponse({"erro": u"%s: %s" % (type(e).__name__,
                                                      str(e)[:200])})

    @app.post("/api/bolus/aplicador/exportar")
    async def _stl_aplicador(request: Request):
        import radai_bolus_aplicador as A
        try:
            c = await request.json() or {}
        except Exception:
            c = {}
        try:
            A.conferir_ato(None, c.get("declaro"), c.get("frase"))
        except radai_bolus.Recusa as e:
            return JSONResponse({"erro": str(e)}, status_code=409)
        r = str(c.get("r") or "")
        with _TRAVA:
            res = _S.get("res") if (r and _S.get("r") == r
                                    and _S.get("b") == str(c.get("b") or "")) \
                else None
        if res is None:
            return JSONResponse({"erro": u"Este aplicador não está mais na "
                                         u"memória. Gere de novo."},
                                status_code=404)
        if res.get("peca") != "aplicador":
            return JSONResponse({"erro": u"Este resultado não é um "
                                         u"aplicador."}, status_code=409)
        try:
            A.conferir_ato(res, c.get("declaro"), c.get("frase"),
                           c.get("declaro_curva"), c.get("frase_curva"))
        except radai_bolus.Recusa as e:
            return JSONResponse({"erro": str(e)}, status_code=409)
        if not res.get("exportavel"):
            return JSONResponse({"erro": u"A malha não fechou: o STL não é "
                                         u"exportado."}, status_code=409)
        nome_zip, dados, nome_stl = A.pacote(res, r)
        linha = A.linha_do_ato(res, nome_stl)
        try:
            _gravar_ato(linha)
        except Exception as e:
            return JSONResponse(
                {"erro": u"O ato não pôde ser registrado (%s: %s), e o STL "
                         u"não sai sem o registro." % (type(e).__name__,
                                                      str(e)[:160])},
                status_code=500)
        if registrar is not None:
            try:
                registrar(linha)
            except Exception:
                pass
        return Response(content=dados, media_type="application/zip",
                        headers={"Cache-Control": "no-store",
                                 "Content-Disposition":
                                     u'attachment; filename="%s"' % nome_zip,
                                 "X-Radai-Nome": nome_zip})

    return app
