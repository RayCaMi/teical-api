import json
import os
import uuid
import requests
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import fitz

load_dotenv()

app = FastAPI(title="Teical API", description="Backend de IA para Leilões")

# Apenas o site oficial e o ambiente de desenvolvimento podem chamar a API pelo navegador
ORIGENS_PERMITIDAS = [
    "https://teical.com.br",
    "https://www.teical.com.br",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENS_PERMITIDAS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

url_supabase: str = os.getenv("SUPABASE_URL")
key_supabase: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url_supabase, key_supabase)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Limites de upload — protegem contra abuso e estouro da cota gratuita
TAMANHO_MAX_PDF = 10 * 1024 * 1024    # 10 MB
TAMANHO_MAX_FOTO = 5 * 1024 * 1024    # 5 MB por foto
MAX_FOTOS = 10
CARGOS_AUTORIZADOS = {"leiloeiro", "admin"}
CATEGORIAS = ["Casa", "Apartamento", "Galpão", "Lajes", "Outros"]


def validar_leiloeiro(authorization: str | None):
    """Valida o token de sessão do Supabase e exige cargo de leiloeiro ou admin."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        usuario = supabase.auth.get_user(token).user
    except Exception:
        usuario = None
    if usuario is None:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")

    # app_metadata é o local seguro (só o admin altera); user_metadata é aceito
    # temporariamente por compatibilidade, mas pode ser editado pelo próprio usuário
    cargo = (usuario.app_metadata or {}).get("role") or (usuario.user_metadata or {}).get("role")
    if cargo not in CARGOS_AUTORIZADOS:
        raise HTTPException(status_code=403, detail="Acesso restrito a leiloeiros e administradores.")
    return usuario


def extrair_texto_pdf(conteudo: bytes) -> str:
    try:
        pdf_doc = fitz.open(stream=conteudo, filetype="pdf")
        return "".join(pagina.get_text() for pagina in pdf_doc)
    except Exception as e:
        print(f"Falha ao extrair texto do PDF: {e}")
        raise HTTPException(status_code=400, detail="Não foi possível ler o PDF enviado. Verifique se o arquivo não está corrompido.")


def analisar_edital(titulo: str, localizacao: str, preco: float, texto_edital: str, contexto_base: str) -> dict:
    """Único ponto de contato com a IA. Para trocar de provedor (Gemini, Claude, etc.),
    basta reescrever esta função mantendo o dicionário de retorno:
    score (int), quartos (int), vagas (int), area (float), categoria (str), parecer (str em Markdown)."""

    prompt = f"""
    Você é um Analista de Dados Imobiliários Sênior e Especialista Estrategista em Leilões Judiciais e Extrajudiciais.
    Sua missão é atuar como um scanner inteligente que lê documentos jurídicos complexos (certidões de cartório, editais com carimbos e links do PJE/ONR) buscando extrair o real valor e oportunidade do ativo.

    DIRETRIZ DE POSTURA (POSITIVA, PORÉM REALISTA):
    Adote uma visão de negócios focada em oportunidades. Não seja excessivamente alarmista com penhoras, hipotecas ou alienações fiduciárias comuns; explique de forma técnica e realista que o arremate em leilão extingue esses ônus, limpando a matrícula. Avalie o score de atratividade financeira com otimismo fundamentado: se o preço por m² estiver abaixo da média de mercado da região, destaque isso como uma excelente margem de lucro, ponderando o tempo estimado para imissão na posse de forma realista.

    [DADOS DIGITADOS PELO USUÁRIO NO SISTEMA]
    - Título sugerido: {titulo}
    - Localização declarada: {localizacao}
    - Preço Base Recebido: R$ {preco}

    {contexto_base}

    *Lógica de Auto-Correção Financeira:* Se o Preço Base for um valor desprovido de pontuação de centavos (ex: 16668210 para um apartamento padrão, significando claramente erro de digitação de 16 milhões), aplique a regra de negócio: assuma a falta de vírgula, corrija mentalmente para R$ 166.682,10 e faça seu cálculo de R$/m² baseado no valor corrigido.

    PREENCHA OS CAMPOS DO JSON ASSIM:
    - score: nota de 0 a 100 baseada no desconto real frente ao mercado.
    - quartos: número de quartos extraído do edital (0 se não encontrar).
    - vagas: número de vagas de garagem (0 se não encontrar).
    - area: área privativa ou útil em m² (0 se não encontrar).
    - categoria: exatamente uma das opções permitidas.
    - parecer: relatório estratégico em Markdown (títulos com ## e listas com marcadores) contendo as seções:
      ## Resumo do Ativo — transcrição clara do tipo de bem, metragens e especificações encontradas.
      ## Análise Financeira — avaliação otimista e realista do potencial de valorização do preço por m² frente ao mercado comparativo.
      ## Diagnóstico Jurídico — listagem construtiva de credores ou penhoras identificadas, detalhando que o leilão resolverá esses ônus.
      ## Estratégia de Arrematação — justificativa da nota do score baseado no equilíbrio entre segurança jurídica e atratividade financeira.

    TEXTO DO DOCUMENTO PARA ANÁLISE JURÍDICA E EXTRAÇÃO:
    {texto_edital[:18000]}
    """

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        # Saída estruturada: a IA é obrigada a devolver um JSON neste formato,
        # eliminando a fragilidade de extrair dados de texto livre com regex
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "score": {"type": "INTEGER"},
                    "quartos": {"type": "INTEGER"},
                    "vagas": {"type": "INTEGER"},
                    "area": {"type": "NUMBER"},
                    "categoria": {"type": "STRING", "enum": CATEGORIAS},
                    "parecer": {"type": "STRING"},
                },
                "required": ["score", "quartos", "vagas", "area", "categoria", "parecer"],
            },
        },
    }

    # A chave vai no header (e não na URL) para nao aparecer em logs de servidor
    headers = {"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY}

    try:
        resposta = requests.post(GEMINI_URL, headers=headers, json=payload, timeout=90)
        dados = resposta.json()
    except requests.RequestException as e:
        print(f"Falha de comunicação com o Gemini: {e}")
        raise HTTPException(status_code=502, detail="O serviço de análise está indisponível no momento. Tente novamente.")

    if resposta.status_code != 200:
        # Loga o motivo real no servidor, mas nao expoe detalhes internos na resposta
        print(f"Erro do Gemini (HTTP {resposta.status_code}): {dados}")
        raise HTTPException(status_code=502, detail="A análise de IA falhou. Tente novamente em alguns minutos.")

    try:
        return json.loads(dados["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        print(f"Resposta da IA fora do formato esperado: {e} | {dados}")
        raise HTTPException(status_code=502, detail="A análise de IA retornou um formato inesperado. Tente novamente.")


def upload_fotos(fotos: list[UploadFile], conteudos: list[bytes]) -> tuple[list[str], list[str]]:
    urls_fotos = []
    erros_upload = []
    for foto, conteudo_foto in zip(fotos, conteudos):
        nome_unico = f"{uuid.uuid4()}_{foto.filename.replace(' ', '_')}"
        try:
            supabase.storage.from_("imoveis").upload(
                path=nome_unico,
                file=conteudo_foto,
                file_options={"content-type": foto.content_type}
            )
            url_publica = supabase.storage.from_("imoveis").get_public_url(nome_unico)
            urls_fotos.append(url_publica)
        except Exception as e:
            erros_upload.append(f"Falha na foto '{foto.filename}': {str(e)}")
    return urls_fotos, erros_upload


@app.get("/")
def home():
    resposta = supabase.table("properties").select("*").order("score", desc=True).execute()
    return {"status": "online", "imoveis_no_banco": resposta.data}


@app.post("/cadastrar-leilao/")
async def cadastrar_leilao(
    titulo: str = Form(...),
    localizacao: str = Form(...),
    preco: float = Form(...),
    link_leiloeiro: str = Form(...),
    quartos_manual: str = Form(""),      # Campos opcionais de correção humana:
    vagas_manual: str = Form(""),        # quando preenchidos, têm prioridade
    area_manual: str = Form(""),         # sobre o que a IA extraiu do edital
    categoria_manual: str = Form(""),
    analise_manual: str = Form(""),      # Parecer escrito pelo próprio leiloeiro (opcional)
    edital: UploadFile = File(...),
    fotos: list[UploadFile] = File(...),
    authorization: str | None = Header(None)
):
    validar_leiloeiro(authorization)

    if not edital.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="O documento precisa de ser um ficheiro PDF.")

    conteudo = await edital.read()
    if len(conteudo) > TAMANHO_MAX_PDF:
        raise HTTPException(status_code=413, detail="O edital excede o limite de 10 MB.")

    if len(fotos) > MAX_FOTOS:
        raise HTTPException(status_code=413, detail=f"Envie no máximo {MAX_FOTOS} fotos.")

    # Valida as fotos antes de gastar a cota da IA
    fotos_validas = []
    conteudos_fotos = []
    erros_upload = []
    for foto in fotos:
        if not foto.filename:
            continue
        if not (foto.content_type or "").startswith("image/"):
            erros_upload.append(f"'{foto.filename}' ignorada: não é uma imagem.")
            continue
        conteudo_foto = await foto.read()
        if len(conteudo_foto) > TAMANHO_MAX_FOTO:
            erros_upload.append(f"'{foto.filename}' ignorada: excede o limite de 5 MB.")
            continue
        fotos_validas.append(foto)
        conteudos_fotos.append(conteudo_foto)

    texto_edital = extrair_texto_pdf(conteudo)

    try:
        resposta_db = supabase.table("properties").select("title, location, price, status, score").limit(5).execute()
        contexto_base = "IMÓVEIS JÁ CADASTRADOS NO NOSSO SISTEMA PARA COMPARAÇÃO:\n"
        for imovel in resposta_db.data:
            contexto_base += f"- {imovel.get('title', 'N/A')} | Preço: R$ {imovel.get('price', 0)} | Score atual: {imovel.get('score', 0)}\n"
    except Exception:
        contexto_base = "Não há imóveis cadastrados na base no momento para comparar."

    analise = analisar_edital(titulo, localizacao, preco, texto_edital, contexto_base)

    # Upload e processamento da galeria de fotos
    urls_fotos, erros_storage = upload_fotos(fotos_validas, conteudos_fotos)
    erros_upload.extend(erros_storage)
    foto_capa = urls_fotos[0] if urls_fotos else "https://images.unsplash.com/photo-1560518883-ce09059eeffa"

    # LÓGICA DE PRIORIDADE (HUMAN-IN-THE-LOOP): se o input manual existir, ignora a extração da IA
    score_numerico = int(analise.get("score", 0))
    q_final = int(quartos_manual) if quartos_manual.isdigit() else int(analise.get("quartos", 0))
    v_final = int(vagas_manual) if vagas_manual.isdigit() else int(analise.get("vagas", 0))
    a_final = float(area_manual) if area_manual.replace('.', '', 1).isdigit() else float(analise.get("area", 0.0))
    c_final = categoria_manual if categoria_manual in CATEGORIAS else analise.get("categoria", "Outros")

    novo_imovel = {
        "title": titulo,
        "location": localizacao,
        "price": preco,
        "score": score_numerico,
        "status": "Em Leilão",
        "image_url": foto_capa,
        "galeria": urls_fotos,
        "memorial_analise": analise.get("parecer", ""),
        "link_leiloeiro": link_leiloeiro,
        "quartos": q_final,
        "vagas": v_final,
        "area": a_final,
        "categoria": c_final
    }
    # Só inclui o parecer manual se foi preenchido (a coluna analise_manual precisa existir no Supabase)
    if analise_manual.strip():
        novo_imovel["analise_manual"] = analise_manual.strip()

    try:
        supabase.table("properties").insert(novo_imovel).execute()
        mensagem_db = "Cadastro guardado com sucesso! Extração estruturada realizada com sucesso."
    except Exception as erro_db:
        print(f"Erro ao guardar no banco: {erro_db}")
        mensagem_db = "A análise foi concluída, mas houve um erro ao guardar no banco de dados."

    return {
        "status": "concluido",
        "banco_de_dados": mensagem_db,
        "erros_upload": erros_upload,
        "dados_recebidos": {
            "titulo": titulo,
            "localizacao": localizacao,
            "preco": preco,
            "link_leiloeiro": link_leiloeiro
        },
        "score_extraido": score_numerico,
        "dados_finais_infraestrutura": {
            "quartos": q_final,
            "vagas": v_final,
            "area": a_final,
            "categoria": c_final
        },
        "analise": analise.get("parecer", "")
    }
