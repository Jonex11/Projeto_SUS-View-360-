# Painel Leitos SUS — instruções de uso

Painel de monitoramento de leitos hospitalares (CNES/DataSUS) que lê os dados
diretamente do CSV exportado pelo ETL, sem precisar editar ou regerar o HTML
a cada atualização.

## Arquivos do pacote

| Arquivo | Para que serve |
|---|---|
| `PainelLeitosSus.html` | O painel em si (abas, gráficos, tabelas, filtros). |
| `Abrir_Painel.bat` | Atalho que você clica duas vezes para abrir o painel. |
| `Abrir_Painel.ps1` | Script que sobe o servidor local e abre o navegador (chamado pelo `.bat`, não precisa mexer nele). |
| `LEITOS_SUS_2026.csv` | Gerado pelo ETL_CNES_LEITOS — **não incluso aqui**, precisa estar na mesma pasta. |

## 1. Onde colocar os arquivos

Coloque os **4 arquivos juntos, na mesma pasta**:

```
C:\ETL_CNES_LEITOS\saida\
├── PainelLeitosSus.html
├── Abrir_Painel.bat
├── Abrir_Painel.ps1
└── LEITOS_SUS_2026.csv
```

Se o ETL já grava o CSV nessa pasta, basta copiar os outros 3 arquivos para
lá uma única vez. Você não precisa mexer neles de novo — só o CSV é
atualizado pelo ETL.

## 2. Como abrir o painel

Dê **duplo-clique em `Abrir_Painel.bat`**.

O que acontece:
1. Abre uma janela preta (prompt) — é o servidor local rodando. Pode deixar
   minimizada.
2. O navegador padrão abre sozinho já com os dados do CSV carregados,
   nas abas Visão Geral, Geografia, Perfil, UTI Especializada, Evolução e
   Ranking & Busca.

Para fechar, feche a janela preta do servidor (fechar só a aba do navegador
não encerra o servidor, mas também não tem problema deixá-lo aberto).

## 3. Atualizando os dados

Sempre que o ETL gerar um novo `LEITOS_SUS_2026.csv`:

- Se o servidor (janela preta) ainda estiver aberto, basta apertar **F5** no
  navegador — o painel relê o CSV na hora (sem cache).
- Se tiver fechado tudo, é só rodar `Abrir_Painel.bat` de novo.

Não é necessário gerar um novo HTML: o `PainelLeitosSus.html` não muda,
apenas o CSV.

## 4. Por que existe o `Abrir_Painel.bat`?

Por segurança, nenhum navegador permite que uma página HTML aberta por
duplo-clique (endereço `file://...`) leia outro arquivo do computador via
JavaScript — mesmo estando na mesma pasta. Isso vale para Chrome, Edge e
Firefox.

O `Abrir_Painel.ps1` contorna isso da forma padrão: sobe um servidor web
local (usando recursos do próprio Windows, sem precisar instalar nada) e
abre o painel através de `http://localhost:...`. Nesse modo o navegador
permite a leitura do CSV normalmente, e tudo fica automático.

## 5. Abrindo o HTML diretamente (sem o `.bat`)

Se por algum motivo você abrir o `PainelLeitosSus.html` direto (duplo-clique
nele, sem passar pelo `.bat`), o painel tenta carregar o CSV automaticamente
e, se não conseguir (o mais comum nesse caso), mostra uma tela pedindo para
você selecionar ou arrastar o arquivo `LEITOS_SUS_2026.csv` manualmente.
Funciona, mas exige esse passo extra — por isso o recomendado é sempre usar
o `Abrir_Painel.bat`.

## 6. Solução de problemas

**"Não foi possível iniciar o servidor local (portas 8743-8752 ocupadas)"**
Algum outro programa está usando essas portas, ou já existe uma instância do
painel aberta. Feche janelas antigas do `Abrir_Painel.bat` ou reinicie o
computador e tente de novo.

**O Windows/antivírus bloqueia o `.ps1` ou pede permissão**
O `Abrir_Painel.bat` já roda o PowerShell com
`-ExecutionPolicy Bypass`, então normalmente não pede nada. Se o
Windows SmartScreen avisar "Editor desconhecido", clique em "Mais
informações" → "Executar assim mesmo" (isso acontece porque o script não
tem assinatura digital, não porque haja algo de errado com ele).

**O navegador abre mas fica na tela de carregamento / pede para selecionar
arquivo**
Confirme se o `LEITOS_SUS_2026.csv` está na mesma pasta dos outros 3
arquivos e se o nome está exatamente `LEITOS_SUS_2026.csv`.

**Mensagem de erro sobre coluna ausente no CSV**
O ETL mudou o formato do CSV (renomeou ou removeu uma coluna). O painel
espera, no mínimo, estas colunas (separadas por `;`):
`COMP, REGIAO, UF, MUNICIPIO, CNES, NOME_ESTABELECIMENTO, TP_GESTAO,
DS_TIPO_UNIDADE, DESC_NATUREZA_JURIDICA, LEITOS_EXISTENTES, LEITOS_SUS,
UTI_TOTAL_EXIST, UTI_TOTAL_SUS, UTI_ADULTO_EXIST, UTI_ADULTO_SUS,
UTI_PEDIATRICO_EXIST, UTI_PEDIATRICO_SUS, UTI_NEONATAL_EXIST,
UTI_NEONATAL_SUS, UTI_QUEIMADO_EXIST, UTI_QUEIMADO_SUS,
UTI_CORONARIANA_EXIST, UTI_CORONARIANA_SUS`

**Quero usar outra porta ou outro nome de arquivo**
Abra `Abrir_Painel.ps1` em um editor de texto e ajuste as variáveis
`$portsParaTentar` ou `$htmlFile` no topo do arquivo.

## 7. O que o painel calcula sozinho a partir do CSV

Nada precisa ser pré-calculado no CSV — o próprio painel faz, a cada
carregamento: KPIs por competência (mês), variação de leitos/UTI SUS,
entradas/saídas de estabelecimentos entre meses, totais por região/UF,
ranking de municípios, distribuição por natureza jurídica, tipo de gestão,
tipo de unidade, e detalhamento de UTI por subtipo (adulto, pediátrica,
neonatal, queimados, coronariana).
