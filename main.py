import os
import re
import uuid
import requests
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from dotenv import load_dotenv
import fitz

load_dotenv()

app = FastAPI(title="Teical API", description="Backend de IA para Leilões")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

url_supabase: str = os.getenv("SUPABASE_URL")
key_supabase: str = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url_supabase, key_supabase)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

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
    quartos_manual: str = Form(""),      # Campo opcional de correção humana
    vagas_manual: str = Form(""),        # Campo opcional de correção humana
    area_manual: str = Form(""),         # Campo opcional de correção humana
    categoria_manual: str = Form(""),    # Campo opcional de correção humana
    edital: UploadFile = File(...),
    fotos: list[UploadFile] = File(...) 
):
    if not edital.filename.endswith('.pdf'):
        return {"erro": "O documento precisa de ser um ficheiro PDF."}
    
    conteudo = await edital.read()
    try:
        pdf_doc = fitz.open(stream=conteudo, filetype="pdf")
        texto_edital = ""
        for pagina in pdf_doc:
            texto_edital += pagina.get_text()
    except Exception as e:
        return {"erro": f"Falha ao extrair texto do PDF: {str(e)}"}

    try:
        resposta_db = supabase.table("properties").select("title, location, price, status, score").limit(5).execute()
        contexto_base = "IMÓVEIS JÁ CADASTRADOS NO NOSSO SISTEMA PARA COMPARAÇÃO:\n"
        for imovel in resposta_db.data:
            contexto_base += f"- {imovel.get('title', 'N/A')} | Preço: R$ {imovel.get('price', 0)} | Score atual: {imovel.get('score', 0)}\n"
    except Exception:
        contexto_base = "Não há imóveis cadastrados na base no momento para comparar."

    url_google = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}
    
    # PROMPT MESTRE: FOCO POSITIVO, REALISTA E ESTRUTURADO COM TAGS DE EXTRAÇÃO
    prompt_mestre = f"""
    Você é um Analista de Dados Imobiliários Sênior e Especialista Estrategista em Leilões Judiciais e Extrajudiciais.
    Sua missão é atuar como um scanner inteligente que lê documentos jurídicos complexos (certidões de cartório, editais com carimbos e links do PJE/ONR) buscando extrair o real valor e oportunidade do ativo.

    DIRETRIZ DE POSTURA (POSITIVA, PORÉM REALISTA):
    Adote uma visão de negócios focada em oportunidades. Não seja excessivamente alarmista com penhoras, hipotecas ou alienações fiduciárias comuns; explique de forma técnica e realista que o arremate em leilão extingue esses ônus, limpando a matrícula. Avalie o score de atratividade financeira com otimismo fundamentado: se o preço por m² estiver abaixo da média de mercado da região, destaque isso como uma excelente margem de lucro, ponderando o tempo estimado para imissão na posse de forma realista.

    [DADOS DIGITADOS PELO USUÁRIO NO SISTEMA]
    - Título sugerido: {titulo}
    - Localização declarada: {localizacao}
    - Preço Base Recebido: R$ {preco}
    - Quartos (Manual): {'Já fornecido: ' + quartos_manual if quartos_manual else 'Buscar e extrair do PDF'}
    - Vagas (Manual): {'Já fornecido: ' + vagas_manual if vagas_manual else 'Buscar e extrair do PDF'}
    - Área m² (Manual): {'Já fornecido: ' + area_manual if area_manual else 'Buscar e extrair do PDF'}
    - Categoria (Manual): {'Já fornecido: ' + categoria_manual if categoria_manual else 'Determinar pelo texto'}

    *Lógica de Auto-Correção Financeira:* Se o Preço Base for um valor desprovido de pontuação de centavos (ex: 16668210 para um apartamento padrão, significando claramente erro de digitação de 16 milhões), aplique a regra de negócio: assuma a falta de vírgula, corrija mentalmente para R$ 166.682,10 e faça seu cálculo de R$/m² baseado no valor corrigido.

    FORMATO DE SAÍDA EXIGIDO (Siga rigorosamente as tags estruturadas para o parser do backend):
    **SCORE TEICAL:** [Insira uma nota de 0 a 100 baseada no desconto real frente ao mercado]
    [QUARTOS: X] (Substitua X pelo número de quartos extraído do PDF. Se não houver ou for manual, replique o bom senso)
    [VAGAS: X] (Substitua X pelo número de vagas de garagem encontradas. Se não achar, retorne 0)
    [AREA: X] (Substitua X pela área privativa ou útil em metros quadrados encontrada no texto)
    [CATEGORIA: X] (Escolha e escreva apenas uma dessas opções: Casa, Apartamento, Galpão, Lajes ou Outros)

    **PARECER IA:**
    Escreva aqui o seu relatório estratégico estruturado em formato Markdown normatizado (use títulos com ## e listas com marcadores). O texto deve conter:
    - **RESUMO DO ATIVO:** Transcrição clara do tipo de bem, metragens e especificações encontradas.
    - **ANÁLISE FINANCEIRA:** Avaliação otimista e realista do potencial de valorização do preço por m² frente ao mercado comparativo.
    - **DIAGNÓSTICO JURÍDICO:** Listagem construtiva de credores ou penhoras identificadas, detalhando que o leilão resolverá esses ônus.
    - **ESTRATÉGIA DE ARREMATAÇÃO:** Justificativa da nota do Score baseado no equilíbrio entre segurança jurídica e atratividade financeira.

    TEXTO DO DOCUMENTO PARA ANÁLISE JURÍDICA E EXTRAÇÃO:
    {texto_edital[:18000]}
    """
    
    payload = {"contents": [{"parts": [{"text": prompt_mestre}]}]}

    resposta_google = requests.post(url_google, headers=headers, json=payload)
    dados_ia = resposta_google.json()

    if resposta_google.status_code != 200:
        return {"status": "erro_google", "codigo_http": resposta_google.status_code, "motivo_real": dados_ia}

    # Upload e processamento da galeria de fotos
    urls_fotos = []
    erros_upload = []
    if fotos and fotos[0].filename != "":
        for foto in fotos:
            conteudo_foto = await foto.read()
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

    foto_capa = urls_fotos[0] if urls_fotos else "https://images.unsplash.com/photo-1560518883-ce09059eeffa"

    try:
        texto_final = dados_ia["candidates"][0]["content"]["parts"][0]["text"]
        
        # PARSER INTELIGENTE USANDO EXPRESSÕES REGULARES (REGEX)
        score_match = re.search(r'\*\*SCORE TEICAL:\*\*\s*(\d+)', texto_final)
        q_match = re.search(r'\[QUARTOS:\s*([\d\.]+)\]', texto_final)
        v_match = re.search(r'\[VAGAS:\s*([\d\.]+)\]', texto_final)
        a_match = re.search(r'\[AREA:\s*([\d\.]+)\]', texto_final)
        c_match = re.search(r'\[CATEGORIA:\s*([^\]]+)\]', texto_final)

        # LÓGICA DE PRIORIDADE (HUMAN-IN-THE-LOOP): Se o input manual existir, ignora a extração da IA
        score_numerico = int(score_match.group(1)) if score_match else 0
        q_final = int(quartos_manual) if quartos_manual.isdigit() else (int(float(q_match.group(1))) if q_match else 0)
        v_final = int(vagas_manual) if vagas_manual.isdigit() else (int(float(v_match.group(1))) if v_match else 0)
        a_final = float(area_manual) if area_manual.replace('.', '', 1).isdigit() else (float(a_match.group(1)) if a_match else 0.0)
        c_final = categoria_manual if categoria_manual else (c_match.group(1).strip() if c_match else "Outros")

        # Limpeza das tags de máquina para entregar um Markdown limpo e elegante ao visualizador React
        texto_limpo = re.sub(r'\[QUARTOS:.*?\]|\[VAGAS:.*?\]|\[AREA:.*?\]|\[CATEGORIA:.*?\]', '', texto_final)
        texto_limpo = texto_limpo.replace(f"**SCORE TEICAL:** {score_numerico}", "").strip()

        novo_imovel = {
            "title": titulo,
            "location": localizacao,
            "price": preco,
            "score": score_numerico,
            "status": "Em Leilão",
            "image_url": foto_capa,       
            "galeria": urls_fotos,        
            "memorial_analise": texto_limpo,
            "link_leiloeiro": link_leiloeiro,
            "quartos": q_final,
            "vagas": v_final,
            "area": a_final,
            "categoria": c_final
        }
        
        supabase.table("properties").insert(novo_imovel).execute()
        mensagem_db = "Cadastro guardado com sucesso! Extração estruturada realizada com sucesso."

    except Exception as erro_db:
        texto_final = dados_ia.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", str(dados_ia))
        mensagem_db = f"Erro ao processar parser ou guardar dados: {str(erro_db)}"
        score_numerico = 0
        q_final, v_final, a_final, c_final = 0, 0, 0.0, "Outros"

    return {
        "status": "concluido",
        "banco_de_dados": mensagem_db,
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
        "analise": texto_final
    }