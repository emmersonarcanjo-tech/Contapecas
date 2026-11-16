# RUNBOOK — Auditoria de ponto Tili Pizzaria (Flit Gestor)

Procedimento das tarefas agendadas "Auditoria de ponto — Semanal" e "Fechamento de ponto —
Mensal (contabilidade)". Cada disparo é uma SESSÃO NOVA, sem memória: siga este arquivo do
começo ao fim. Ninguém está acompanhando — decida pelo caminho mais razoável e, se algo
essencial falhar, avise por SendUserMessage e pare.

Parâmetro de entrada: **MODO** = `semanal` ou `mensal` (vem no prompt da tarefa).

> ⚠️ **REGRA DE OURO — nunca deixe a janela "Salvar como" do Windows aparecer.**
> Eu NÃO consigo clicar em janelas do Windows (só dentro do site), e essa janela CONGELA o app
> inteiro (trava a tarefa e até a conexão com o computador). Por isso **NUNCA** uso o download do
> navegador. Eu **capturo os dados do relatório na memória da página** (interceptando
> `URL.createObjectURL` e bloqueando o clique de download) e trabalho com eles. Vale para TODOS os relatórios.

---

## 0. Ferramentas e contexto
Carregue via ToolSearch (2 chamadas):
- `mcp__remote-devices__Claude_Browser__` (tools do navegador interno)
- `select:mcp__remote-devices__get_device_info,mcp__remote-devices__device_list_dir,mcp__remote-devices__device_stage_files,mcp__remote-devices__device_commit_files,SendUserFile,SendUserMessage`

Contexto:
- Flit Gestor: https://manager.flitapp.com.br — **já logado** no navegador interno. Use SOMENTE o navegador interno (`Claude_Browser`).
- Empresa: **Tili Pizzaria**, CNPJ final **0002-07**.
- **Nunca** clique em salvar/confirmar/excluir no Flit (gravações). Só navegar e exportar (leituras).
- **Clique em botão sempre por referência** (`find` → `computer{left_click, ref}`), nunca por coordenada.
- Pasta no PC: `C:\Users\emers\Documents\Tili Ponto` (`motor\auditoria_ponto.py`, `motor\RUNBOOK.md`, `Semanal\`, `Mensal\`).

## 1. Verificar o computador
`get_device_info`. Se falhar (PC desligado/offline): SendUserMessage avisando que a auditoria (MODO) não rodou por isso, e **pare**. Senão, `device_list_dir` em `C:\Users\emers\Documents\Tili Ponto`.

## 2. Período
```
# semanal (segunda anterior a domingo anterior):
python3 -c "from datetime import date,timedelta; h=date.today(); i=h-timedelta(days=7); f=h-timedelta(days=1); print(i.strftime('%d/%m/%Y'),f.strftime('%d/%m/%Y'),i.isoformat(),f.isoformat())"
# mensal (mês anterior completo):
python3 -c "from datetime import date,timedelta; h=date.today(); f=date(h.year,h.month,1)-timedelta(days=1); i=date(f.year,f.month,1); print(i.strftime('%d/%m/%Y'),f.strftime('%d/%m/%Y'),i.isoformat(),f.isoformat())"
```
Guarde `INI_BR`/`FIM_BR` (DD/MM/AAAA) e `INI_ISO`/`FIM_ISO` (AAAA-MM-DD).

## 3. Puxar a "Apuração de jornadas" NA MEMÓRIA (sem baixar)
1. `Claude_Browser__navigate` para `https://manager.flitapp.com.br/relatorios-adicionais`; aguarde ~8s (se `mat-select` não existir, espere mais e tente de novo).
2. Rode este JS (troque INI_BR e FIM_BR). Bloqueia o download, captura o arquivo em memória, parseia e devolve as linhas como JSON — nenhum download acontece:
```js
(async()=>{const s=ms=>new Promise(r=>setTimeout(r,ms));
window.__blobs=[];const o=URL.createObjectURL.bind(URL);URL.createObjectURL=b=>{const u=o(b);window.__blobs.push(b);return u;};
const oc=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if((this.href||'').startsWith('blob:'))return;return oc.apply(this,arguments);};
const sel=document.querySelector('mat-select');sel.click();await s(800);
Array.from(document.querySelectorAll('.cdk-overlay-container mat-option')).find(o=>o.innerText.trim()==='Apuração de jornadas').click();await s(700);
const set=(e,v)=>{const st=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;st.call(e,v);e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));e.blur();e.dispatchEvent(new Event('blur',{bubbles:true}));};
const ins=document.querySelectorAll('input[placeholder="Data inicial"],input[placeholder="Data final"]');set(ins[0],'INI_BR');set(ins[1],'FIM_BR');await s(900);
const n0=window.__blobs.length;document.querySelector('button[aria-label="Export button"]').click();
const t0=Date.now();while(window.__blobs.length===n0&&Date.now()-t0<30000)await s(400);if(window.__blobs.length===n0)return 'timeout';
const buf=new Uint8Array(await window.__blobs[window.__blobs.length-1].arrayBuffer());const dv=new DataView(buf.buffer);const td=new TextDecoder();const files={};let p=0;
while(p+30<=buf.length&&dv.getUint32(p,true)===0x04034b50){const m=dv.getUint16(p+8,true),cs=dv.getUint32(p+18,true),nl=dv.getUint16(p+26,true),el=dv.getUint16(p+28,true);const nm=td.decode(buf.subarray(p+30,p+30+nl));const d0=p+30+nl+el;const dt=buf.subarray(d0,d0+cs);let tx;if(m===0)tx=td.decode(dt);else tx=await new Response(new Blob([dt]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).text();files[nm]=tx;p=d0+cs;}
const dec=s=>s.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&apos;/g,"'");
const ss=[];for(const m of (files['xl/sharedStrings.xml']||'').matchAll(/<si>([\s\S]*?)<\/si>/g))ss.push(dec(Array.from(m[1].matchAll(/<t[^>]*>([\s\S]*?)<\/t>/g)).map(x=>x[1]).join('')));
const sheet=Object.entries(files).find(([n])=>/worksheets\/sheet1\.xml/.test(n))[1];const R=[];
for(const rm of sheet.matchAll(/<row[^>]*>([\s\S]*?)<\/row>/g)){const c={};for(const cm of rm[1].matchAll(/<c r="([A-Z]+)\d+"([^>]*)>([\s\S]*?)<\/c>/g)){let v=(cm[3].match(/<v>([\s\S]*?)<\/v>/)||[])[1];if(v===undefined)v=(cm[3].match(/<t[^>]*>([\s\S]*?)<\/t>/)||[])[1]||'';else if(/t="s"/.test(cm[2]))v=ss[+v];c[cm[1].replace(/\d+/,'')]=dec(String(v));}R.push(c);}
const H=R[0];const out=R.slice(1).filter(r=>r.A).map(r=>{const o={};Object.keys(H).forEach(k=>o[H[k]]=r[k]||'');return o;});
window.__apuracao=out;return {linhas:out.length, colunas:Object.keys(out[0]).length};})()
```
3. Pegue o JSON com `JSON.stringify(window.__apuracao)` e grave em `/mnt/user-data/outputs/apuracao.json`. Se o retorno for grande e o harness salvar num arquivo, decodifique de lá com Bash — **nunca** copie à mão.

## 4. Montar a planilha
```
device_stage_files  C:\Users\emers\Documents\Tili Ponto\motor\auditoria_ponto.py
python3 <motor_staged> --modo MODO --apuracao /mnt/user-data/outputs/apuracao.json --inicio INI_BR --fim FIM_BR --saida /mnt/user-data/outputs/<NOME>.xlsx
#  NOME semanal: Auditoria_Ponto_INI_ISO_a_FIM_ISO   |   mensal: Fechamento_Ponto_AAAA-MM
python3 /mnt/skills/public/xlsx/scripts/recalc.py /mnt/user-data/outputs/<NOME>.xlsx 60   # deve dar success, 0 erros
```
O script aceita a apuração em **.json** (capturada na página) ou em **.xlsx**. Guarde o resumo em texto que ele imprime.

## 5. (Somente MENSAL) Espelho PDF + AFD — também na memória
Mesmo princípio: NUNCA baixar. Instale o gancho `URL.createObjectURL` + bloqueio do clique ANTES de exportar, dispare a exportação (botão **por referência**), pegue o blob em `window.__blobs`, converta para base64 (`btoa` byte a byte) em `window.__b64`. Recupere `window.__b64`: se vier grande, o harness salva num arquivo — decodifique com Bash (`base64.b64decode`) e grave o arquivo final. **Não** copie base64 à mão.
- **Espelho PDF:** `/relatorios-de-ponto` → selecione todos via API do ag-grid (`forEachNode(n=>n.data&&n.setSelected(true))`), abra Exportar (botão "Botão exportar"), escolha **PDF - Unificado**, preencha Descrição, clique **EXPORTAR RELATÓRIOS** por referência, aguarde "Pronto!", capture o blob do PDF. Nome: `Espelho_Ponto_AAAA-MM.pdf`.
- **AFD:** `/exportar-dados` → Formato **AFD (Portaria 671)**, datas do mês, Empresa 0002-07, EXPORTAR por referência, capture o blob `.zip`. Nome: `AFD_AAAA-MM.zip`.

## 6. Entregar
- `device_commit_files`: semanal → `Semanal\<NOME>.xlsx`; mensal → `Mensal\` com os 3 (xlsx + `Espelho_Ponto_AAAA-MM.pdf` + `AFD_AAAA-MM.zip`).
- `SendUserFile` do(s) arquivo(s) principais.
- `SendUserMessage` curto (padrão do Emerson) com o resumo do script + destaque dos **ALERTAS** e das **jornadas pendentes** (tratar em Frequência > Ajustes de jornadas).

## Observações
- O motor reconhece na apuração: **Folga**, **Férias**, **Feriado**, **Atestado** (não contam como falta). Falta = dia com horário previsto e sem marcação.
- Folgas são lançadas em *Gestão de escalas* (Tipo Folga), férias em *Férias e folgas* (Tipo Férias), desligamento no cadastro do colaborador. As tarefas agendadas NÃO fazem isso — só leem e geram relatório.
- API do Flit não contratada; por isso tudo sai por exportação lida na memória da página.
