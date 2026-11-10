import pandas as pd
import streamlit as st

# Configuração da Página
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide",
)

# ID da Planilha oficial fornecida
SHEET_ID = "1JzqqiSqjuBb7GNaswi-EHKYn7SEOqt0RtYeHvt7ywj0"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"


@st.cache_data(ttl=600)
def carregar_dados_ft():
  try:
    df = pd.read_csv(SHEET_URL)
    return df
  except Exception as e:
    # Retorna um DataFrame vazio e exibe o erro exato na interface
    st.error(f"Erro crítico ao carregar dados do Google Sheets: {e}")
    return pd.DataFrame()


# Execução inicial para teste de carga
df_produtos = carregar_dados_ft()

if df_produtos.empty:
  st.warning(
      "Atenção: A base de dados retornou vazia ou inacessível. Verifique se a"
      " planilha está publicada na Web como CSV."
  )
else:
  st.sidebar.success(
      f"Base carregada com sucesso! ({len(df_produtos)} produtos)"
  )
