# ETL - Hospitais e Leitos SUS (CNES / OpenDataSUS)

Script em Python que automatiza o pipeline completo de **download, extração, validação, consolidação e carga** dos microdados de leitos hospitalares do SUS (CNES), publicados pelo portal **OpenDataSUS**, com carregamento opcional direto em um **Oracle Autonomous Database** via Wallet (mTLS).

## Funcionalidades

- Download automático dos arquivos ZIP anuais a partir do bucket S3 do OpenDataSUS
- Verificação prévia de disponibilidade do arquivo (requisição `HEAD`)
- Cache local de downloads (evita baixar novamente; use `--forcar` para sobrescrever)
- Cálculo de hash **SHA256** para checagem de integridade do arquivo baixado
- Extração automática dos arquivos ZIP
- Detecção automática de **encoding** (`utf-8-sig`, `utf-8`, `cp1252`, `latin1`)
- Detecção automática de **delimitador** do CSV (`;`, `,`, `|`, tab)
- Normalização dos nomes de colunas (maiúsculas, sem caracteres especiais, com deduplicação)
- Validação de volume mínimo de registros por arquivo
- Consolidação de múltiplos CSVs de um mesmo ano em um único arquivo, adicionando a coluna `ANO_REFERENCIA`
- Carga opcional dos dados consolidados em tabela Oracle, em lotes (`executemany`)
- Criação automática da tabela Oracle caso ela não exista (colunas `VARCHAR2(4000)`)
- Log completo em arquivo e console
- Processamento de um ano específico, lista de anos, intervalo de anos ou todos os anos disponíveis

## Requisitos

- Python 3.8+
- Pacotes:
  - `requests`
  - `python-dotenv`
  - `oracledb` (opcional — necessário apenas para carregar dados no Oracle)

```bash
pip install requests python-dotenv oracledb
```

## Configuração

O script carrega variáveis de ambiente a partir de um arquivo `.env` na mesma pasta (via `python-dotenv`). A variável esperada é:

```
DB_PASS=sua_senha_aqui
```

Ela é usada tanto como senha padrão do usuário Oracle quanto como senha padrão da Wallet.

As demais configurações (diretórios locais, URL do S3, timeouts, DSN padrão, usuário e tabela padrão) ficam no dicionário `CONFIG`, no topo do arquivo.

> ⚠️ **Observação de segurança:** o DSN Oracle padrão, o usuário padrão (`SPRINT2`) e o caminho da Wallet estão *hardcoded* no script. Antes de compartilhar ou versionar este arquivo publicamente, considere mover esses valores para variáveis de ambiente (assim como já é feito com `DB_PASS`) e garantir que o arquivo `.env` e a pasta da Wallet não sejam commitados.

### Diretórios utilizados (Windows)

Os caminhos padrão são fixos para Windows (`C:/...`). Ajuste o dicionário `CONFIG` se for executar em Linux/macOS.

```
C:\ETL_CNES_LEITOS\
├── downloads\        # ZIPs baixados (cache)
├── extracao\{ano}\   # CSVs extraídos de cada ZIP
├── saida\            # LEITOS_SUS_{ano}.csv consolidados
└── logs\              # etl_cnes_leitos.log
```

## Uso

```bash
python ET_Base_Leitos_v7.py [opções]
```

Se nenhuma opção de ano for informada, o script processa apenas o **ano atual**.

### Opções de linha de comando

| Opção | Descrição |
|---|---|
| `--ano ANO` | Processa somente um ano específico (ex: `--ano 2024`) |
| `--anos ANOS` | Lista de anos separados por vírgula (ex: `--anos 2022,2023,2024`) |
| `--ano-inicial ANO` / `--ano-final ANO` | Processa um intervalo de anos |
| `--todos` | Processa todos os anos de 2007 até o ano atual |
| `--forcar` | Força novo download mesmo que o arquivo já exista em cache |
| `--carregar-oracle` | Após consolidar, carrega os dados na tabela Oracle |
| `--oracle-dsn DSN` | DSN de conexão Oracle (padrão: definido em `CONFIG`) |
| `--oracle-usuario USUARIO` | Usuário do banco Oracle (padrão: `SPRINT2`) |
| `--oracle-senha SENHA` | Senha do banco Oracle (padrão: variável `DB_PASS`; se ausente, solicitada via prompt) |
| `--oracle-tabela TABELA` | Tabela de destino no Oracle (padrão: `LEITO_SUS`) |
| `--oracle-lote N` | Quantidade de registros por lote de inserção (padrão: `5000`) |
| `--oracle-criar-tabela` | Cria a tabela Oracle automaticamente caso não exista |
| `--oracle-wallet CAMINHO` | Diretório dos arquivos da Wallet Oracle |
| `--oracle-wallet-senha SENHA` | Senha da Wallet Oracle |

### Exemplos

```bash
# Processar apenas o ano de 2026
python ET_Base_Leitos_v7.py --ano 2026

# Processar múltiplos anos específicos
python ET_Base_Leitos_v7.py --anos 2022,2023,2024

# Processar um intervalo de anos
python ET_Base_Leitos_v7.py --ano-inicial 2020 --ano-final 2024

# Processar todos os anos disponíveis (2007 até hoje)
python ET_Base_Leitos_v7.py --todos

# Processar e carregar no Oracle, criando a tabela se não existir
python ET_Base_Leitos_v7.py --ano 2024 --carregar-oracle --oracle-criar-tabela

# Forçar novo download mesmo com cache existente
python ET_Base_Leitos_v7.py --ano 2024 --forcar
```

## Pipeline de processamento (por ano)

1. **Localizar URL** — verifica se o arquivo do ano existe no S3 via `HEAD`
2. **Download** — baixa o ZIP em streaming, com até 3 tentativas e cache local
3. **Descompactação** — extrai o ZIP para `extracao/{ano}/`
4. **Localização dos CSVs** — busca recursivamente todos os `.csv` extraídos
5. **Validação** — detecta encoding/delimitador e verifica volume mínimo de registros
6. **Consolidação** — une todos os CSVs do ano em `saida/LEITOS_SUS_{ano}.csv` (delimitado por `;`, UTF-8 com BOM), adicionando a coluna `ANO_REFERENCIA`
7. **Carga no Oracle** *(opcional)* — insere os registros em lotes na tabela configurada

Ao final, o script exibe um resumo com os anos processados com sucesso e os anos com falha, e encerra com código de saída `1` caso algum ano tenha falhado.

## Logs

Todos os eventos são registrados simultaneamente no console e no arquivo:

```
C:\ETL_CNES_LEITOS\logs\etl_cnes_leitos.log
```

## Observações

- A carga no Oracle é opcional; sem `oracledb` instalado ou sem `--carregar-oracle`, o script executa apenas o download, extração e consolidação.
- Colunas divergentes entre CSVs do mesmo ano geram um aviso no log, mas não interrompem o processamento (linhas são completadas ou truncadas para o número de colunas do cabeçalho de referência).
- Campos vazios são convertidos para `NULL` na carga ao Oracle.
