import re
import pandas as pd
import streamlit as st

# Configuração da Página
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide"
)

# ID da Planilha Oficial Consolidada Correta
SHEET_ID = "1B-qyvNzkGi3FQJr92zVH_eaulh8YXZain7KoeTUecP4"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"


@st.cache_data(ttl=600)
def carregar_dados_ft():
    try:
        # Lê o CSV ignorando quebras de linha internas problemáticas nas células
        df = pd.read_csv(SHEET_URL, on_bad_lines="skip")
        df.columns = [c.strip() for c in df.columns]
        for col in df.select_dtypes(include=["object"]).columns:
            df[col] = df[col].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
        return df
    except Exception as e:
        st.error(f"Erro ao carregar dados do Google Sheets: {e}")
        return pd.DataFrame()


def extrair_soma_ativos_pct(texto_garantias):
    if not isinstance(texto_garantias, str) or not texto_garantias.strip():
        return 0.0

    padroes = re.findall(
        r"(?:Mín\.?|Máx\.?)?\s*(\d+(?:[.,]\d+)?)\s*(%|g/kg)",
        texto_garantias,
        re.IGNORECASE
    )

    soma_pct = 0.0
    for valor_str, unidade in padroes:
        try:
            val = float(valor_str.replace(",", "."))
            if unidade.lower() == "g/kg":
                soma_pct += val / 10.0
            else:
                soma_pct += val
        except ValueError:
            continue
    return soma_pct


def extrair_lista_ativos(df):
    if "Principios_Ativos_Garantias" not in df.columns:
        return []
    ativos_encontrados = set()
    for texto in df["Principios_Ativos_Garantias"].dropna():
        partes = re.split(r"[|;/\n]", str(texto))
        for p in partes:
            if ":" in p:
                nome_ativo = p.split(":")[0].strip()
                if nome_ativo:
                    ativos_encontrados.add(nome_ativo)
    return sorted(list(ativos_encontrados))


def ordenar_portfolio(df):
    def peso_ordem(row):
        texto = f"{row.get('Marca_Linha', '')} {row.get('Categoria', '')} {row.get('Produto', '')}".lower()
        if "xtendra" in texto or "anox" in texto or "nasure" in texto:
            return 1
        if "novamold" in texto or "propical" in texto:
            return 2
        if "salplus" in texto:
            return 3
        if "dresbond" in texto:
            return 4
        return 5

    df_copia = df.copy()
    df_copia["_ordem"] = df_copia.apply(peso_ordem, axis=1)
    df_copia = df_copia.sort_values(by=["_ordem", "Produto"]).drop(columns=["_ordem"])
    return df_copia


def inicializar_sessao(lista_produtos):
    defaults = {
        "tipo_gatilho": "Aves Abatidas",
        "aves_dia": 50000.0,
        "dias_mes": 25,
        "racao_input": 7500.0,
        "mp_input": 3750.0,
        "consumo_ave": 5.0,
        "peso_ave": 3.0,
        "rend_mp_pv": 30.0,
        "rend_fvo": 25.0,
        "rend_fps": 10.0,
        "rend_oleo": 12.67,
        "next_id": 3
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "volumes_producao" not in st.session_state:
        st.session_state.volumes_producao = {
            "Fábrica de Ração": 6250.0,
            "Matéria-Prima Bruta FFO": 1125.0,
            "Farinha de Vísceras (FVO)": 281.25,
            "Farinha de Penas (FPS)": 112.5,
            "Óleo de Frango": 142.54
        }

    prod_inicial = lista_produtos[0] if lista_produtos else None
    if "cesta_aplicacao" not in st.session_state:
        st.session_state.cesta_aplicacao = [
            {
                "id": 1,
                "matriz": "Farinha de Vísceras (FVO)",
                "produto": prod_inicial,
                "dosagem": 500.0,
                "preco_kg": 35.0,
                "share": 100
            },
            {
                "id": 2,
                "matriz": "Óleo de Frango",
                "produto": prod_inicial,
                "dosagem": 1000.0,
                "preco_kg": 38.0,
                "share": 100
            }
        ]


def recalcular_balanco():
    gatilho = st.session_state.tipo_gatilho
    consumo_ave = st.session_state.consumo_ave
    peso_ave = st.session_state.peso_ave
    rend_mp_pv = st.session_state.rend_mp_pv
    rend_fvo = st.session_state.rend_fvo
    rend_fps = st.session_state.rend_fps
    rend_oleo = st.session_state.rend_oleo

    if gatilho == "Aves Abatidas":
        aves_mes = st.session_state.aves_dia * st.session_state.dias_mes
        racao_calc = (aves_mes * consumo_ave) / 1000.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    elif gatilho == "Produção de Ração":
        racao_calc = st.session_state.racao_input
        aves_mes = (racao_calc * 1000.0) / consumo_ave if consumo_ave > 0 else 0.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    else:
        mp_calc = st.session_state.mp_input
        fator_mp = peso_ave * (rend_mp_pv / 100.0)
        aves_mes = (mp_calc * 1000.0) / fator_mp if fator_mp > 0 else 0.0
        racao_calc = (aves_mes * consumo_ave) / 1000.0

    fvo_calc = mp_calc * (rend_fvo / 100.0)
    fps_calc = mp_calc * (rend_fps / 100.0)
    oleo_calc = mp_calc * (rend_oleo / 100.0)

    st.session_state.aves_mes_calc = aves_mes
    st.session_state.volumes_producao = {
        "Fábrica de Ração": racao_calc,
        "Matéria-Prima Bruta FFO": mp_calc,
        "Farinha de Vísceras (FVO)": fvo_calc,
        "Farinha de Penas (FPS)": fps_calc,
        "
