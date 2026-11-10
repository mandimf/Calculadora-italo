import re
import pandas as pd
import streamlit as st

# Configuração da Página
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide",
)

# ID da Planilha Oficial consolidada no Google Drive/Sheets
SHEET_ID = "1B-qyvNzkGi3FQJr92zVH_eaulh8YXZain7KoeTUecP4"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"


@st.cache_data(ttl=600)
def carregar_dados_ft():
  try:
    df = pd.read_csv(SHEET_URL)
    return df
  except Exception as e:
    st.error(
        f"Erro ao conectar com a base de dados no Google Sheets: {e}. Verifique"
        " se a planilha está acessível publicamente para leitura."
    )
    return pd.DataFrame()
