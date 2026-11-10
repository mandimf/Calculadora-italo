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
dados_cache = None  # Placeholder para cache se necessário


def carregar_dados_ft():
  try:
    # Leitura direta da planilha publicada/compartilhada via CSV
    df = pd.read_csv(SHEET_URL)
    return df
  except Exception as e:
    st.error(
        f"Erro ao conectar com a base de dados no Google Sheets: {e}. Verifique"
        " se a planilha está acessível publicamente para leitura."
    )
    return pd.DataFrame()


def extrair_soma_ativos_declarados(texto_garantias):
  """Varre o texto de garantias, extrai todos os valores percentuais ou numéricos

  declarados de princípios ativos e retorna a soma total para cálculo de ppm.
  Se não houver valor numérico declarado, ignora.
  """
  if not isinstance(texto_garantias, str) or not texto_garantias.strip():
    return 0.0

  # Procura por padrões numéricos seguidos de % ou g/kg (ex: 98,0%, Mín. 30%, 20.5%)
  # Expressão regular para capturar números decimais (com ponto ou vírgula)
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

  # Carregamento da Base de Dados
  df_produtos = carregar_dados_ft()

  if df_produtos.empty:
    st.warning(
        "A base de dados retornou vazia ou não pôde ser carregada. Por favor,"
        " verifique o link do Google Sheets."
    )
    return

  # Sidebar de Navegação entre as Etapas do Fluxo
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

    # Motor de Cálculo Integrado
    # Base de cálculo unificada em ton/mês
    # Estimativa cruzada
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
      "Filtre os produtos do portfólio por categoria, estado físico e princípios"
      " ativos para encontrar o equivalente direto."
  )

  # Filtros na Lateral ou Topo
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

  # Filtragem Aplicada
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
elif modulo == "3. Calculadora de Consumo & ppm":
  st.header("Etapa 3: Calculadora de Consumo e Dosagem em ppm")
  st.markdown(
      "Selecione o produto, defina a dosagem em **g/ton** e verifique o consumo"
      " mensal e a entrega de princípios ativos em **ppm**."
  )

  col_c1, col_c2 = st.columns(2)
  with col_c1:
    volume_substrato = st.number_input(
        "Volume Mensal do Substrato / Matéria-Prima (ton/mês)",
        min_value=0.1,
        value=1000.0,
        step=100.0,
    )
  with col_c2:
    if "Produto" in df_produtos.columns:
      produto_escolhido = st.selectbox(
          "Selecione o Produto Comercial:",
          options=df_produtos["Produto"].tolist(),
      )
    else:
      produto_escolhido = None

  if produto_escolhido:
    # Localizar dados do produto
    prod_info = df_produtos[df_produtos["Produto"] == produto_escolhido].iloc[0]
    garantias = (
        str(prod_info["Principios_Ativos_Garantias"])
        if "Principios_Ativos_Garantias" in df_produtos.columns
        else ""
    )
    composicao_desc = (
        str(prod_info["Composicao"])
        if "Composicao" in df_produtos.columns
        else ""
    )

    st.info(
        f"**Produto:** {produto_escolhido} | **Categoria:**"
        f" {prod_info.get('Categoria', 'N/A')}\n\n**Composição (Referência):**"
        f" {composicao_desc}\n\n**Garantias Declaradas:** {garantias}"
    )

    dosagem_g_ton = st.number_input(
        "Dosagem Aplicada (g / tonelada de substrato):",
        min_value=0.0,
        value=500.0,
        step=50.0,
    )

    # Cálculos
    consumo_kg_mes = (volume_substrato * dosagem_g_ton) / 1000.0
    soma_ativos_pct = extrair_soma_ativos_declarados(garantias)
    # ppm = g/ton * (% / 100) -> se garantias estão em %, 1% = 10000 ppm. Ajuste matemático:
    # Ex: 98% = 98 partes por cem -> em g/ton: dosagem (g/ton) * (98/100) = g de ativo por tonelada = mg/kg = ppm.
    # Correção precisa: Dosagem em g/ton * (Soma_Ativos_% / 100) resulta em gramas de ativo por tonelada, o que equivale numericamente a ppm (mg/kg).
    ppm_entregue = dosagem_g_ton * (soma_ativos_pct / 100.0)

    st.success("📈 **Resultados do Dimensionamento Técnico:**")
    res_m1, res_m2, res_m3 = st.columns(3)
    with res_m1:
      st.metric("Consumo Mensal do Produto", f"{consumo_kg_mes:,.2f} kg / mês")
    with res_m2:
      st.metric(
          "Soma de Ativos Declarados",
          f"{soma_ativos_pct:.2f}%"
          if soma_ativos_pct > 0
          else "Não quantificado em %",
      )
    with res_m3:
      st.metric(
          "Princípio Ativo Entregue",
          f"{ppm_entregue:,.1f} ppm (mg/kg)"
          if soma_ativos_pct > 0
          else "Sob consulta",
      )

# -------------------------------------------------------------
# MÓDULO 4: SIMULAÇÃO DE FATURAMENTO & FECHAMENTO
# -------------------------------------------------------------
elif modulo == "4. Simulação de Faturamento & Fechamento":
  st.header("Etapa 4: Simulador de Faturamento e Viabilidade Comercial")
  st.markdown(
      "Traduza o consumo em volume financeiro, aplicando preço de venda e"
      " cenários de share de carteira."
  )

  col_f1, col_f2, col_f3 = st.columns(3)
  with col_f1:
    consumo_sim_kg = st.number_input(
        "Consumo Total do Produto (kg/mês)",
        min_value=0.0,
        value=500.0,
        step=50.0,
    )
  with col_f2:
    preco_venda_kg = st.number_input(
        "Preço de Venda Praticado (R$ / kg ou L)",
        min_value=0.0,
        value=35.0,
        step=1.0,
    )
  with col_f3:
    share_carteira = st.slider(
        "Share de Carteira Pretendido (%)", min_value=10, max_value=100, value=100
    )

  faturamento_mensal = consumo_sim_kg * preco_venda_kg * (share_carteira / 100.0)
  faturamento_anual = faturamento_mensal * 12.0

  st.markdown("---")
  st.subheader("💰 **Resumo Executivo do Negócio:**")
  f_res1, f_res2 = st.columns(2)
  with f_res1:
    st.metric("Faturamento Potencial Mensal", f"R$ {faturamento_mensal:,.2f}")
  with f_res2:
    st.metric("Faturamento Anualizado", f"R$ {faturamento_anual:,.2f}")


if __name__ == "__main__":
  main()
