# Teical API

Backend do [Teical](https://teical.com.br/) — plataforma de imóveis em leilão. API em FastAPI que recebe o cadastro de um leilão (edital em PDF + fotos), extrai o texto do edital, gera uma análise estratégica com IA (Gemini) e grava o imóvel avaliado no Supabase.

## Stack

- **FastAPI** — framework da API
- **Supabase** — banco de dados (tabela `properties`) e storage de fotos (bucket `imoveis`)
- **Google Gemini** — análise do edital e score de atratividade
- **PyMuPDF** — extração de texto dos PDFs

## Como rodar localmente

```powershell
# 1. Criar e ativar o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1

# 2. Instalar as dependências
pip install -r requirements.txt

# 3. Configurar as variáveis de ambiente
# Copie .env.example para .env e preencha com suas chaves
Copy-Item .env.example .env

# 4. Iniciar o servidor
uvicorn main:app --reload
```

A API sobe em `http://127.0.0.1:8000`. A documentação interativa fica em `http://127.0.0.1:8000/docs`.

## Variáveis de ambiente

| Variável | Descrição |
| --- | --- |
| `SUPABASE_URL` | URL do projeto no Supabase |
| `SUPABASE_KEY` | Chave de API do Supabase |
| `GEMINI_API_KEY` | Chave da API do Google Gemini |

## Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| `GET` | `/` | Status da API e lista de imóveis ordenados por score |
| `POST` | `/cadastrar-leilao/` | Cadastra um leilão: recebe dados do formulário, edital (PDF) e fotos; retorna a análise da IA |
