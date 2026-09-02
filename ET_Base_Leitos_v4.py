"""
ETL - Microdados de Hospitais e Leitos SUS (CNES / OpenDataSUS)
=============================================================
Download, descompactação, detecção de encoding/delimitador,
validação e consolidação de arquivos CSV de leitos hospitalares do SUS
com carga direta no Oracle Autonomous Database via Wallet (mTLS).
"""

import argparse
import csv
import getpass
import hashlib
import logging
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

import requests

# Driver Oracle
try:
    import oracledb
except ImportError:
    oracledb = None

# =====================================================================
# CONFIGURAÇÕES
# =====================================================================
CONFIG = {
    # Diretórios Locais
    "DIRETORIO_BASE": Path.home() / "Downloads" / "ETL_CNES_LEITOS",
    "DIRETORIO_DOWNLOAD": Path.home() / "Downloads" / "ETL_CNES_LEITOS" / "downloads",
    "DIRETORIO_EXTRACAO": Path.home() / "Downloads" / "ETL_CNES_LEITOS" / "extracao",
    "DIRETORIO_SAIDA": Path.home() / "Downloads" / "ETL_CNES_LEITOS" / "saida",
    "DIRETORIO_LOG": Path.home() / "Downloads" / "ETL_CNES_LEITOS" / "logs",
    
    # Portal S3 OpenDataSUS
    "URL_S3": "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/Leitos_SUS/",
    
    # Download
    "TIMEOUT": 180,
    "TENTATIVAS_DOWNLOAD": 3,
    
    # Validação
    "QTD_MINIMA_REGISTROS": 1,
    
    # Oracle Autonomous Database + Wallet
    "ORACLE_USUARIO_PADRAO": "SPRINT2",
    "ORACLE_PASSWORD": "ciLQgAeLZ8J2kwk",
    "ORACLE_TABELA": "LEITO_SUS",
    "ORACLE_TAMANHO_LOTE": 5000,
    "ORACLE_WALLET_DIR": r"C:\Oracle\Wallet_Odb1",
    "ORACLE_WALLET_PASSWORD": "ciLQgAeLZ8J2kwk",
    "ORACLE_DSN_PADRAO": (
        "(description=(retry_count=20)(retry_delay=3)"
        "(address=(protocol=tcps)(port=1522)(host=adb.sa-saopaulo-1.oraclecloud.com))"
        "(connect_data=(service_name=g01d83e16d5494f_odb1_low.adb.oraclecloud.com))"
        "(security=(ssl_server_dn_match=yes)))"
    ),
}


# =====================================================================
# CONFIGURAR LOG
# =====================================================================
def configurar_log():
    """Configura o sistema de logging para gravar em arquivo e console."""
    CONFIG["DIRETORIO_LOG"].mkdir(parents=True, exist_ok=True)
    arquivo_log = CONFIG["DIRETORIO_LOG"] / "etl_cnes_leitos.log"

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    file_handler = logging.FileHandler(arquivo_log, encoding="utf-8")
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)


# =====================================================================
# CRIAR DIRETÓRIOS
# =====================================================================
def criar_diretorios():
    """Cria a árvore de diretórios necessária."""
    for chave in [
        "DIRETORIO_BASE",
        "DIRETORIO_DOWNLOAD",
        "DIRETORIO_EXTRACAO",
        "DIRETORIO_SAIDA",
        "DIRETORIO_LOG",
    ]:
        CONFIG[chave].mkdir(parents=True, exist_ok=True)


# =====================================================================
# GERAR URL
# =====================================================================
def gerar_url(ano):
    """Gera a URL direta do arquivo ZIP para o ano solicitado."""
    return f"{CONFIG['URL_S3']}Leitos_csv_{ano}.zip"


# =====================================================================
# LOCALIZAR ARQUIVO NO S3
# =====================================================================
def localizar_url_ano(ano):
    """Verifica se o arquivo do ano existe via requisição HEAD."""
    url = gerar_url(ano)
    logging.info(f"Verificando recurso do ano {ano}...")
    try:
        response = requests.head(url, timeout=30, allow_redirects=True)
        if response.status_code == 200:
            logging.info(f"Arquivo encontrado: {url}")
            return url
        logging.warning(
            f"Arquivo não encontrado para o ano {ano}. HTTP {response.status_code}"
        )
    except Exception as erro:
        logging.warning(f"Erro ao verificar arquivo do ano {ano}: {erro}")
    return None


# =====================================================================
# CALCULAR HASH
# =====================================================================
def calcular_hash(caminho):
    """Calcula a assinatura SHA256 do arquivo para integridade."""
    sha256 = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        while True:
            bloco = arquivo.read(1024 * 1024)
            if not bloco:
                break
            sha256.update(bloco)
    return sha256.hexdigest()


# =====================================================================
# DOWNLOAD
# =====================================================================
def baixar_arquivo(url, ano, forcar=False):
    """Realiza o download em stream do arquivo ZIP do S3 com retentativas."""
    destino = CONFIG["DIRETORIO_DOWNLOAD"] / f"Leitos_csv_{ano}.zip"

    # Verificar se já existe em cache
    if destino.exists() and not forcar:
        logging.info(f"Arquivo já existe em cache: {destino}")
        logging.info("Use --forcar para baixar novamente.")
        return destino, calcular_hash(destino)

    for tentativa in range(1, CONFIG["TENTATIVAS_DOWNLOAD"] + 1):
        try:
            logging.info(
                f"Download {ano} - tentativa {tentativa}/{CONFIG['TENTATIVAS_DOWNLOAD']}"
            )
            with requests.get(url, stream=True, timeout=CONFIG["TIMEOUT"]) as response:
                response.raise_for_status()
                tamanho_total = int(response.headers.get("content-length", 0))
                tamanho_baixado = 0
                ultimo_percentual_logado = -10

                with open(destino, "wb") as arquivo:
                    for bloco in response.iter_content(chunk_size=1024 * 1024):
                        if bloco:
                            arquivo.write(bloco)
                            tamanho_baixado += len(bloco)
                            if tamanho_total:
                                percentual = (tamanho_baixado / tamanho_total) * 100
                                if (percentual - ultimo_percentual_logado >= 10) or (percentual >= 100):
                                    logging.info(
                                        f"Download {ano}: {percentual:.1f}% "
                                        f"({tamanho_baixado / 1024 / 1024:.1f} MB / {tamanho_total / 1024 / 1024:.1f} MB)"
                                    )
                                    ultimo_percentual_logado = percentual

            tamanho = destino.stat().st_size
            if tamanho == 0:
                raise Exception("Arquivo baixado está vazio (0 bytes).")

            hash_arquivo = calcular_hash(destino)
            logging.info("Download concluído com sucesso!")
            logging.info(f"Tamanho: {tamanho / 1024 / 1024:.2f} MB")
            logging.info(f"SHA256: {hash_arquivo}")
            return destino, hash_arquivo

        except Exception as erro:
            logging.error(f"Erro no download (tentativa {tentativa}): {erro}")
            if tentativa < CONFIG["TENTATIVAS_DOWNLOAD"]:
                time.sleep(5)

    raise Exception(
        f"Falha ao baixar o arquivo do ano {ano} após {CONFIG['TENTATIVAS_DOWNLOAD']} tentativas."
    )


# =====================================================================
# DESCOMPACTAR
# =====================================================================
def descompactar(arquivo_zip, ano):
    """Extrai o arquivo ZIP para a pasta de extração do ano correspondente."""
    diretorio = CONFIG["DIRETORIO_EXTRACAO"] / str(ano)

    if diretorio.exists():
        shutil.rmtree(diretorio)
    diretorio.mkdir(parents=True, exist_ok=True)

    logging.info(f"Descompactando: {arquivo_zip} -> {diretorio}")
    try:
        with zipfile.ZipFile(arquivo_zip, "r") as zip_ref:
            zip_ref.extractall(diretorio)
    except zipfile.BadZipFile:
        raise Exception("Arquivo ZIP corrompido ou formato inválido.")

    logging.info(f"Extração concluída: {diretorio}")
    return diretorio


# =====================================================================
# LOCALIZAR CSV
# =====================================================================
def localizar_csvs(diretorio):
    """Busca recursivamente todos os arquivos CSV dentro do diretório extraído."""
    arquivos = list(diretorio.rglob("*.csv")) + list(diretorio.rglob("*.CSV"))
    arquivos = list(dict.fromkeys(arquivos))

    if not arquivos:
        raise Exception(f"Nenhum arquivo CSV encontrado em {diretorio}.")

    logging.info(f"CSV(s) encontrado(s): {len(arquivos)}")
    for arq in arquivos:
        logging.info(f" -> {arq.name}")
    return arquivos


# =====================================================================
# DETECTAR ENCODING
# =====================================================================
def detectar_encoding(arquivo):
    """Identifica o encoding do arquivo CSV testando codecs usuais."""
    encodings = ["utf-8-sig", "utf-8", "cp1252", "latin1"]
    for encoding in encodings:
        try:
            with open(arquivo, "r", encoding=encoding) as f:
                f.read(100000)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin1"


# =====================================================================
# DETECTAR DELIMITADOR
# =====================================================================
def detectar_delimitador(arquivo, encoding):
    """Detecta automaticamente o separador de colunas do CSV."""
    with open(arquivo, "r", encoding=encoding, errors="replace") as f:
        amostra = f.read(100000)
    try:
        dialect = csv.Sniffer().sniff(amostra, delimiters=";,|\t")
        return dialect.delimiter
    except csv.Error:
        return ";"


# =====================================================================
# NORMALIZAR COLUNA
# =====================================================================
def normalizar_coluna(nome):
    """Padroniza o nome da coluna para letras maiúsculas sem caracteres especiais."""
    nome = str(nome).strip()
    nome = nome.replace("\ufeff", "")
    nome = nome.upper()
    nome = re.sub(r"[^A-Z0-9_]", "_", nome)
    nome = re.sub(r"_+", "_", nome)
    nome = nome.strip("_")
    if not nome:
        nome = "COLUNA"
    return nome


# =====================================================================
# NORMALIZAR CABEÇALHO
# =====================================================================
def normalizar_colunas(colunas):
    """Normaliza e desduplica colunas repetidas."""
    resultado = []
    contador = {}
    for coluna in colunas:
        nome = normalizar_coluna(coluna)
        if nome in contador:
            contador[nome] += 1
            nome = f"{nome}_{contador[nome]}"
        else:
            contador[nome] = 0
        resultado.append(nome)
    return resultado


# =====================================================================
# CONTAR REGISTROS
# =====================================================================
def contar_registros(arquivo, encoding, delimitador):
    """Conta a quantidade de linhas de dados do CSV (excluindo cabeçalho)."""
    total = 0
    with open(arquivo, "r", encoding=encoding, errors="replace", newline="") as f:
        leitor = csv.reader(f, delimiter=delimitador)
        next(leitor, None)
        for _ in leitor:
            total += 1
    return total


# =====================================================================
# VALIDAR CSV
# =====================================================================
def validar_csv(arquivo, ano):
    """Verifica integridade, encoding, delimitador e volume de registros do CSV."""
    logging.info(f"Validando CSV: {arquivo.name}")
    encoding = detectar_encoding(arquivo)
    delimitador = detectar_delimitador(arquivo, encoding)
    logging.info(f"Encoding: {encoding} | Delimitador: {repr(delimitador)}")

    total = contar_registros(arquivo, encoding, delimitador)
    logging.info(f"Registros encontrados: {total:,}")

    if total < CONFIG["QTD_MINIMA_REGISTROS"]:
        raise Exception(
            f"CSV do ano {ano} ({arquivo.name}) não possui registros suficientes "
            f"(mínimo: {CONFIG['QTD_MINIMA_REGISTROS']})."
        )
    return encoding, delimitador, total


# =====================================================================
# COLUNAS A REMOVER
# =====================================================================
COLUNAS_REMOVER = [
    "COMP",
    "CO_IBGE",
    "MOTIVO_DESABILITACAO",
    "CNES",
    "NO_LOGRADOURO",
    "NU_ENDERECO",
    "NO_COMPLEMENTO",
    "NO_BAIRRO",
    "CO_CEP",
    "NU_TELEFONE",
    "NO_EMAIL",
]


def filtrar_colunas(cabecalho):
    indices_manter = [
        indice
        for indice, nome in enumerate(cabecalho)
        if nome not in COLUNAS_REMOVER
    ]
    cabecalho_filtrado = [cabecalho[indice] for indice in indices_manter]
    return cabecalho_filtrado, indices_manter


# =====================================================================
# CONSOLIDAR CSVs
# =====================================================================
def consolidar_csvs(arquivos, ano):
    """Consolida múltiplos CSVs de um ano em um único arquivo padronizado."""
    destino = CONFIG["DIRETORIO_SAIDA"] / f"LEITOS_SUS_{ano}.csv"
    logging.info(f"Criando arquivo consolidado: {destino}")

    primeira_linha = True
    total_registros = 0
    cabecalho_referencia = None
    indices_manter = None

    with open(destino, "w", encoding="utf-8-sig", newline="") as saida:
        escritor = None
        for arquivo in arquivos:
            encoding = detectar_encoding(arquivo)
            delimitador = detectar_delimitador(arquivo, encoding)

            with open(arquivo, "r", encoding=encoding, errors="replace", newline="") as entrada:
                leitor = csv.reader(entrada, delimiter=delimitador)
                try:
                    cabecalho = next(leitor)
                except StopIteration:
                    continue

                cabecalho = normalizar_colunas(cabecalho)

                if primeira_linha:
                    cabecalho_referencia = cabecalho
                    cabecalho_saida = cabecalho + ["ANO_REFERENCIA"]
                    cabecalho_saida, indices_manter = filtrar_colunas(cabecalho_saida)
                    
                    logging.info(
                        f"Colunas removidas do arquivo final: {', '.join(COLUNAS_REMOVER)}"
                    )

                    escritor = csv.writer(
                        saida, delimiter=";", quoting=csv.QUOTE_MINIMAL
                    )
                    escritor.writerow(cabecalho_saida)
                    primeira_linha = False

                if cabecalho != cabecalho_referencia:
                    logging.warning(
                        f"Estrutura de colunas divergente encontrada em: {arquivo.name}"
                    )

                for linha in leitor:
                    if len(linha) < len(cabecalho_referencia):
                        linha += [""] * (len(cabecalho_referencia) - len(linha))
                    elif len(linha) > len(cabecalho_referencia):
                        linha = linha[: len(cabecalho_referencia)]

                    linha.append(str(ano))
                    linha = [linha[indice] for indice in indices_manter]

                    escritor.writerow(linha)
                    total_registros += 1

    logging.info(f"Consolidação concluída para o ano {ano}.")
    logging.info(f"Total de registros gravados: {total_registros:,}")
    logging.info(f"Arquivo gerado: {destino}")
    return destino, total_registros


# =====================================================================
# ORACLE - CONECTAR COM WALLET
# =====================================================================
def conectar_oracle(dsn, usuario, senha, wallet_dir=None, wallet_pass=None):
    """
    Abre uma conexão com o Oracle Autonomous Database usando modo Thin e Wallet.
    """
    if oracledb is None:
        raise Exception(
            "Biblioteca 'oracledb' não instalada. Instale com: pip install oracledb"
        )
    
    logging.info(f"Conectando ao Oracle: usuário={usuario}")
    if wallet_dir:
        logging.info(f"Usando Wallet localizada em: {wallet_dir}")

    parametros = {
        "user": usuario,
        "password": senha,
        "dsn": dsn,
    }

    if wallet_dir:
        parametros["wallet_location"] = wallet_dir
        if wallet_pass:
            parametros["wallet_password"] = wallet_pass

    conexao = oracledb.connect(**parametros)
    logging.info("Conexão com Oracle estabelecida com sucesso!")
    return conexao


# =====================================================================
# ORACLE - CRIAR TABELA (SE NÃO EXISTIR)
# =====================================================================
def criar_tabela_oracle_se_nao_existir(conexao, tabela, colunas):
    """Cria a tabela com colunas VARCHAR2(4000) caso não exista."""
    cursor = conexao.cursor()
    try:
        cursor.execute(
            "SELECT COUNT(*) FROM user_tables WHERE table_name = :1",
            [tabela.upper()],
        )
        (existe,) = cursor.fetchone()
        if existe:
            logging.info(f"Tabela {tabela} já existe. Estrutura mantida.")
            return

        definicao_colunas = ", ".join(f'"{coluna}" VARCHAR2(4000)' for coluna in colunas)
        comando = f'CREATE TABLE "{tabela.upper()}" ({definicao_colunas})'
        logging.info(f"Tabela {tabela} não encontrada. Criando com colunas VARCHAR2(4000)...")
        cursor.execute(comando)
        conexao.commit()
        logging.info(f"Tabela {tabela} criada com sucesso.")
    finally:
        cursor.close()


# =====================================================================
# ORACLE - CARREGAR DADOS
# =====================================================================
def carregar_dados_oracle(arquivo_csv, conexao, tabela, tamanho_lote, criar_tabela=False):
    """
    Lê o CSV consolidado e insere os registros na tabela Oracle em lotes.
    """
    with open(arquivo_csv, "r", encoding="utf-8-sig", newline="") as entrada:
        leitor = csv.reader(entrada, delimiter=";")
        try:
            cabecalho = next(leitor)
        except StopIteration:
            logging.warning(f"Arquivo {arquivo_csv} está vazio. Nada a carregar no Oracle.")
            return 0

        if criar_tabela:
            criar_tabela_oracle_se_nao_existir(conexao, tabela, cabecalho)

        colunas_sql = ", ".join(f'"{c}"' for c in cabecalho)
        marcadores = ", ".join(f":{i + 1}" for i in range(len(cabecalho)))
        comando_insert = f'INSERT INTO "{tabela.upper()}" ({colunas_sql}) VALUES ({marcadores})'

        logging.info(f"Carregando dados na tabela Oracle: {tabela}")

        cursor = conexao.cursor()
        lote = []
        total_inseridos = 0

        try:
            for linha in leitor:
                # Converte string vazia para None para virar NULL no banco
                valores = [v if v.strip() != "" else None for v in linha]
                lote.append(tuple(valores))

                if len(lote) >= tamanho_lote:
                    cursor.executemany(comando_insert, lote)
                    conexao.commit()
                    total_inseridos += len(lote)
                    logging.info(f"Registros inseridos até agora: {total_inseridos:,}")
                    lote = []

            if lote:
                cursor.executemany(comando_insert, lote)
                conexao.commit()
                total_inseridos += len(lote)
        except Exception as e:
            conexao.rollback()
            logging.error(f"Erro durante a carga no Oracle: {e}")
            raise
        finally:
            cursor.close()

    logging.info(f"Carga no Oracle concluída. Total de registros inseridos: {total_inseridos:,}")
    return total_inseridos


# =====================================================================
# PROCESSAR ANO
# =====================================================================
def processar_ano(
    ano,
    forcar=False,
    conexao_oracle=None,
    tabela_oracle=None,
    tamanho_lote_oracle=None,
    criar_tabela_oracle=False,
):
    """Executa o pipeline completo de ETL para um ano específico."""
    inicio = time.time()
    logging.info("=" * 75)
    logging.info(f"PROCESSANDO ANO: {ano}")
    logging.info("=" * 75)

    # 1. Localizar URL
    url = localizar_url_ano(ano)
    if not url:
        raise Exception(f"Arquivo do ano {ano} não encontrado no repositório remoto.")

    # 2. Download
    arquivo, hash_arquivo = baixar_arquivo(url, ano, forcar)

    # 3. Descompactar
    diretorio = descompactar(arquivo, ano)

    # 4. Localizar CSVs
    arquivos_csv = localizar_csvs(diretorio)

    # 5. Validação
    for arquivo_csv in arquivos_csv:
        validar_csv(arquivo_csv, ano)

    # 6. Consolidação
    arquivo_final, total = consolidar_csvs(arquivos_csv, ano)

    # 7. Carga no Oracle
    total_oracle = None
    if conexao_oracle is not None:
        total_oracle = carregar_dados_oracle(
            arquivo_final,
            conexao_oracle,
            tabela_oracle,
            tamanho_lote_oracle,
            criar_tabela=criar_tabela_oracle,
        )

    tempo = time.time() - inicio
    logging.info("=" * 75)
    logging.info(f"ANO {ano} FINALIZADO COM SUCESSO")
    logging.info(f"Registros no CSV: {total:,}")
    logging.info(f"Arquivo final: {arquivo_final}")
    logging.info(f"SHA256 ZIP: {hash_arquivo}")
    if total_oracle is not None:
        logging.info(f"Registros inseridos no Oracle ({tabela_oracle}): {total_oracle:,}")
    logging.info(f"Tempo total: {tempo:.2f} segundos")
    logging.info("=" * 75)
    return True


# =====================================================================
# ARGUMENTOS DE LINHA DE COMANDO
# =====================================================================
def obter_argumentos():
    """Configura e lê os argumentos passados via CLI."""
    parser = argparse.ArgumentParser(
        description="Download, extração, consolidação e carga da base de Hospitais e Leitos SUS no Oracle."
    )
    parser.add_argument(
        "--ano",
        type=int,
        help="Processar somente um ano específico (ex: --ano 2024).",
    )
    parser.add_argument(
        "--anos",
        type=str,
        help="Anos separados por vírgula (ex: --anos 2022,2023,2024).",
    )
    parser.add_argument(
        "--ano-inicial",
        type=int,
        help="Ano inicial do intervalo de processamento.",
    )
    parser.add_argument(
        "--ano-final",
        type=int,
        help="Ano final do intervalo de processamento.",
    )
    parser.add_argument(
        "--todos",
        action="store_true",
        help="Processar todos os anos disponíveis (de 2007 até o ano atual).",
    )
    parser.add_argument(
        "--forcar",
        action="store_true",
        help="Forçar novo download mesmo se o arquivo já existir em cache.",
    )
    parser.add_argument(
        "--carregar-oracle",
        action="store_true",
        help="Após consolidar, carrega os dados na tabela Oracle (padrão: LEITO_SUS).",
    )
    parser.add_argument(
        "--oracle-dsn",
        type=str,
        default=CONFIG["ORACLE_DSN_PADRAO"],
        help="DSN Oracle.",
    )
    parser.add_argument(
        "--oracle-usuario",
        type=str,
        default=CONFIG["ORACLE_USUARIO_PADRAO"],
        help=f"Usuário do banco Oracle (padrão: {CONFIG['ORACLE_USUARIO_PADRAO']}).",
    )
    parser.add_argument(
        "--oracle-senha",
        type=str,
        default=CONFIG["ORACLE_PASSWORD"],
        help="Senha do banco Oracle.",
    )
    parser.add_argument(
        "--oracle-tabela",
        type=str,
        default=CONFIG["ORACLE_TABELA"],
        help=f"Tabela de destino no Oracle (padrão: {CONFIG['ORACLE_TABELA']}).",
    )
    parser.add_argument(
        "--oracle-lote",
        type=int,
        default=CONFIG["ORACLE_TAMANHO_LOTE"],
        help=f"Quantidade de registros por lote (padrão: {CONFIG['ORACLE_TAMANHO_LOTE']}).",
    )
    parser.add_argument(
        "--oracle-criar-tabela",
        action="store_true",
        help="Cria a tabela Oracle automaticamente caso não exista.",
    )
    parser.add_argument(
        "--oracle-wallet",
        type=str,
        default=CONFIG["ORACLE_WALLET_DIR"],
        help="Diretório dos arquivos da Wallet do Oracle.",
    )
    parser.add_argument(
        "--oracle-wallet-senha",
        type=str,
        default=CONFIG["ORACLE_WALLET_PASSWORD"],
        help="Senha da Wallet do Oracle.",
    )
    return parser.parse_args()


# =====================================================================
# DEFINIR ANOS A PROCESSAR
# =====================================================================
def definir_anos(args):
    """Calcula a lista de anos a serem processados a partir dos argumentos."""
    if args.ano:
        return [args.ano]
    if args.anos:
        return sorted(set(int(ano.strip()) for ano in args.anos.split(",")))
    if args.ano_inicial and args.ano_final:
        if args.ano_final < args.ano_inicial:
            raise ValueError("O ano final não pode ser menor que o ano inicial.")
        return list(range(args.ano_inicial, args.ano_final + 1))
    if args.todos:
        return list(range(2007, datetime.now().year + 1))

    return [datetime.now().year]


# =====================================================================
# MAIN
# =====================================================================
def main():
    """Função principal do orquestrador ETL."""
    configurar_log()
    criar_diretorios()
    args = obter_argumentos()

    try:
        anos = definir_anos(args)
    except ValueError as e:
        logging.error(str(e))
        sys.exit(1)

    logging.info("=" * 75)
    logging.info("ETL - HOSPITAIS E LEITOS SUS (CNES)")
    logging.info("=" * 75)
    logging.info(f"Anos selecionados: {anos}")
    logging.info(f"Diretório de saída: {CONFIG['DIRETORIO_SAIDA']}")

    conexao_oracle = None
    if args.carregar_oracle:
        senha = args.oracle_senha or os.environ.get("ORACLE_PASSWORD") or CONFIG.get("ORACLE_PASSWORD")
        if not senha:
            senha = getpass.getpass("Senha Oracle: ")

        wallet_senha = args.oracle_wallet_senha or CONFIG.get("ORACLE_WALLET_PASSWORD")

        try:
            conexao_oracle = conectar_oracle(
                dsn=args.oracle_dsn,
                usuario=args.oracle_usuario,
                senha=senha,
                wallet_dir=args.oracle_wallet,
                wallet_pass=wallet_senha,
            )
        except Exception as erro:
            logging.error(f"Falha ao conectar no Oracle: {erro}")
            sys.exit(1)

    sucesso = []
    falha = []

    try:
        for ano in anos:
            try:
                resultado = processar_ano(
                    ano,
                    args.forcar,
                    conexao_oracle=conexao_oracle,
                    tabela_oracle=args.oracle_tabela,
                    tamanho_lote_oracle=args.oracle_lote,
                    criar_tabela_oracle=args.oracle_criar_tabela,
                )
                if resultado:
                    sucesso.append(ano)
            except Exception as erro:
                logging.exception(f"Erro ao processar ano {ano}: {erro}")
                falha.append(ano)
    finally:
        if conexao_oracle is not None:
            conexao_oracle.close()
            logging.info("Conexão Oracle encerrada.")

    logging.info("=" * 75)
    logging.info("RESUMO DO PROCESSAMENTO")
    logging.info(f"Anos processados com sucesso: {sucesso}")
    logging.info(f"Anos com erro / não encontrados: {falha}")
    logging.info("=" * 75)

    if falha:
        sys.exit(1)


# =====================================================================
# EXECUÇÃO
# =====================================================================
if __name__ == "__main__":
    main()