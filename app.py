import re
import pandas as pd
import streamlit as st

# Configuração da Página
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide",
)

# ID da Planilha correta fornecida por você
SHEET_ID = "1JzqqiSqjuBb7GNaswi-EHKYn7SEOqt0RtYeHvt7ywj0"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"


@st.cache_data(ttl=600)
def carregar_dados_ft():
  try:
    df = pd.read_csv(SHEET_URL)
    return df
  except Exception as e:
    st.error(f"Erro crítico ao carregar dados do Google Sheets: {e}")
    return pd.DataFrame()


def extrair_soma_ativos_declarados(texto_garantias):
  """Varre o texto de garantias, extrai os valores percentuais ou numéricos

  declarados de princípios ativos e retorna a soma para cálculo de ppm.
  """
  if not isinstance(texto_garantias, str) or not texto_garantias.strip():
    return 0.0

  padroes = re.findall(
      r"(?:Mín\.?|Máx\.?)?\s*(\d+(?:[.,]\d+)?)\s*(?:%|g/kg)",
      texto_garantias,
      re.IGNORECASE,
  )

  soma = 0.0
  for p in padroes:
    val_str = p.replace(",", ".")
    try:
      soma += float(val_str)
    except ValueError:
      continue
  return soma


def main():
  st.title("🐔 Ecossistema Comercial - Nutrição Avícola & Graxaria")
  st.markdown(
      "Ferramenta integrada de suporte técnico-comercial em campo: Balanço de"
      " Massa, Consulta de FT, Consumo em ppm e Viabilidade de Faturamento."
  )

  df_produtos = carregar_dados_ft()

  if df_produtos.empty:
    st.warning(
        "A base de dados retornou vazia ou inacessível. Verifique se a"
        " planilha está pública para leitura."
    )
    return

  st.sidebar.success(
      f"Base carregada com sucesso! ({len(df_produtos)} produtos)"
  )
  st.sidebar.header("🧭 Módulos do Ecossistema")
  modulo = st.sidebar.radio(
      "Selecione a Etapa:",
      [
          "1. Balanço de Massa & Produção",
          "2. Consultor de FT & Match Técnico",
          "3. Calculadora de Consumo & ppm",
          "4. Simulação de Faturamento & Fechamento",
      ],
  )

  # -------------------------------------------------------------
  # MÓDULO 1: BALANÇO DE MASSA & PRODUÇÃO (Com os 3 Gatilhos)
  # -------------------------------------------------------------
  if modulo == "1. Balanço de Massa & Produção":
    st.header("Etapa 1: Simulador de Produção e Balanço de Massa")
    st.markdown(
        "Insira **qualquer um dos três gatilhos abaixo** para dimensionar toda"
        " a operação do cliente de forma direta ou reversa."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
      st.subheader("Gatilho A: Aves")
      aves_dia = st.number_input(
          "Abate de Aves (aves/dia)",
          min_value=0.0,
          value=50000.0,
          step=5000.0,
      )
      dias_mes = st.number_input(
          "Dias de Operação / Mês", min_value=1, value=25, step=1
      )
      total_aves_mes = aves_dia * dias_mes

    with col2:
      st.subheader("Gatilho B: Ração")
      racao_fabrica_ton = st.number_input(
          "Produção de Fábrica de Ração (ton/mês)",
          min_value=0.0,
          value=7500.0,
          step=500.0,
      )

    with col3:
      st.subheader("Gatilho C: Matéria-Prima FFO")
      mp_ffo_mes = st.number_input(
          "Matéria-Prima Bruta Recebida na FFO (ton/mês)",
          min_value=0.0,
          value=3750.0,
          step=250.0,
      )

    st.markdown("---")
    st.subheader("⚙️ Parâmetros Industriais e Zootécnicos (Editáveis)")

    p_col1, p_col2, p_col3 = st.columns(3)
    with p_col1:
      consumo_racao_ave = st.number_input(
          "Consumo Ração / Ave no Ciclo (kg)", value=5.0, step=0.1
      )
      peso_vivo_ave = st.number_input(
          "Peso Vivo Médio ao Abate (kg)", value=3.0, step=0.1
      )
    with p_col2:
      rend_mp_pv = st.number_input(
          "Rendimento MP Bruta sobre Peso Vivo (%)", value=30.0, step=1.0
      )
      rend_fvo = st.number_input(
          "Rendimento de FVO sobre MP Bruta (%)", value=25.0, step=1.0
      )
    with p_col3:
      rend_fps = st.number_input(
          "Rendimento de FPS sobre MP Bruta (%)", value=10.0, step=1.0
      )
      rend_oleo = st.number_input(
          "Rendimento de Óleo de Frango sobre MP Bruta (%)", value=12.67, step=0.1
      )

    est_racao_por_aves = (total_aves_mes * consumo_racao_ave) / 1000.0
    est_mp_por_aves = (
        (total_aves_mes * peso_vivo_ave) * (rend_mp_pv / 100.0)
    ) / 1000.0

    st.success(
        "📊 **Painel de Volumes Calculados para o Cliente (Estimativa Mensal):**"
    )

    res_col1, res_col2, res_col3, res_col4, res_col5 = st.columns(5)
    with res_col1:
      st.metric(
          "Ração Produzida",
          f"{racao_fabrica_ton:,.1f} ton",
          delta=f"Base Aves: {est_racao_por_aves:,.1f} ton",
      )
    with res_col2:
      st.metric(
          "Matéria-Prima FFO",
          f"{mp_ffo_mes:,.1f} ton",
          delta=f"Base Aves: {est_mp_por_aves:,.1f} ton",
      )
    with res_col3:
      fvo_calc = mp_ffo_mes * (rend_fvo / 100.0)
      st.metric("Farinha Vísceras (FVO)", f"{fvo_calc:,.1f} ton")
    with res_col4:
      fps_calc = mp_ffo_mes * (rend_fps / 100.0)
      st.metric("Farinha Penas (FPS)", f"{fps_calc:,.1f} ton")
    with res_col5:
      oleo_calc = mp_ffo_mes * (rend_oleo / 100.0)
      st.metric("Óleo de Frango", f"{oleo_calc:,.1f} ton")

  # -------------------------------------------------------------
  # MÓDULO 2: CONSULTOR DE FT & MATCH TÉCNICO
  # -------------------------------------------------------------
  elif modulo == "2. Consultor de FT & Match Técnico":
    st.header("Etapa 2: Consultor Inteligente de Ficha Técnica (Match Direto)")
    st.markdown(
        "Filtre os produtos do portfólio por categoria, estado físico e"
        " princípios ativos para encontrar o equivalente direto."
    )

    cat_disponiveis = (
        df_produtos["Categoria"].dropna().unique().tolist()
        if "Categoria" in df_produtos.columns
        else []
    )
    cat_selecionada = st.multiselect(
        "Filtrar por Categoria / Linha:",
        options=cat_disponiveis,
        default=cat_disponiveis,
    )

    estados_disponiveis = (
        df_produtos["Estado_Fisico"].dropna().unique().tolist()
        if "Estado_Fisico" in df_produtos.columns
        else []
    )
    estado_selecionado = st.multiselect(
        "Filtrar por Estado Físico:",
        options=estados_disponiveis,
        default=estados_disponiveis,
    )

    df_filtrado = df_produtos.copy()
    if cat_selecionada:
      df_filtrado = df_filtrado[df_filtrado["Categoria"].isin(cat_selecionada)]
    if estado_selecionado:
      df_filtrado = df_filtrado[
          df_filtrado["Estado_Fisico"].isin(estado_selecionado)
      ]

    st.dataframe(df_filtrado, use_container_width=True)

  # -------------------------------------------------------------
  # MÓDULO 3: CALCULADORA DE CONSUMO & ppm
  # -------------------------------------------------------------
  elif modulo == "3
