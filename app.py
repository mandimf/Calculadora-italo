import re
import pandas as pd
import streamlit as st

# Configuração da Página
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide"
)

# Planilha base informada por você
SHEET_ID = "1JzqqiSqjuBb7GNaswi-EHKYn7SEOqt0RtYeHvt7ywj0"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"


@st.cache_data(ttl=600)
def carregar_dados_ft():
    try:
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
        "Óleo de Frango": oleo_calc
    }


def main():
    st.title("🐔 Ecossistema Comercial - Nutrição Avícola & Graxaria")
    st.markdown("Suporte técnico-comercial integrado: Balanço de Massa, Consulta de FTs, Dosagem Multi-Ponto (ppm) e Faturamento.")

    df_bruto = carregar_dados_ft()
    if df_bruto.empty:
        st.warning("A base de dados retornou vazia ou inacessível. Verifique se a planilha está pública para leitura.")
        return

    df_produtos = ordenar_portfolio(df_bruto)
    lista_produtos = df_produtos["Produto"].dropna().tolist() if "Produto" in df_produtos.columns else []

    inicializar_sessao(lista_produtos)
    recalcular_balanco()

    st.sidebar.success(f"Base conectada: {len(df_produtos)} produtos")
    st.sidebar.header("🧭 Navegação")

    modulo = st.sidebar.radio(
        "Selecione a Etapa:",
        [
            "1. Balanço de Massa & Produção",
            "2. Consulta de FT & Calculadora de Consumo (ppm)",
            "3. Simulação de Faturamento & Fechamento"
        ]
    )

    if modulo == "1. Balanço de Massa & Produção":
        st.header("Etapa 1: Simulador de Produção e Balanço de Massa")
        st.markdown("Selecione o dado inicial do cliente. Todos os valores ficam salvos automaticamente ao navegar entre as abas.")

        st.session_state.tipo_gatilho = st.radio(
            "Qual dado de partida você tem?",
            ["Aves Abatidas", "Produção de Ração", "Matéria-Prima FFO Recebida"],
            index=["Aves Abatidas", "Produção de Ração", "Matéria-Prima FFO Recebida"].index(st.session_state.tipo_gatilho),
            horizontal=True
        )

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🎯 Entrada do Gatilho Principal")
            if st.session_state.tipo_gatilho == "Aves Abatidas":
                st.session_state.aves_dia = st.number_input("Abate Diário (aves/dia):", min_value=1.0, value=float(st.session_state.aves_dia), step=5000.0)
                st.session_state.dias_mes = st.number_input("Dias de Operação / Mês:", min_value=1, value=int(st.session_state.dias_mes), step=1)
            elif st.session_state.tipo_gatilho == "Produção de Ração":
                st.session_state.racao_input = st.number_input("Volume de Ração Produzida (ton/mês):", min_value=1.0, value=float(st.session_state.racao_input), step=500.0)
            else:
                st.session_state.mp_input = st.number_input("Matéria-Prima Bruta Recebida na FFO (ton/mês):", min_value=1.0, value=float(st.session_state.mp_input), step=250.0)

        with col2:
            st.subheader("⚙️ Índices Zootécnicos e Industriais")
            p_c1, p_c2 = st.columns(2)
            with p_c1:
                st.session_state.consumo_ave = st.number_input("Consumo Ração/Ave (kg):", min_value=0.1, value=float(st.session_state.consumo_ave), step=0.1)
                st.session_state.peso_ave = st.number_input("Peso Vivo Médio (kg):", min_value=0.1, value=float(st.session_state.peso_ave), step=0.1)
                st.session_state.rend_mp_pv = st.number_input("Rendimento MP s/ PV (%):", min_value=1.0, value=float(st.session_state.rend_mp_pv), step=0.5)
            with p_c2:
                st.session_state.rend_fvo = st.number_input("Rendimento FVO s/ MP (%):", min_value=1.0, value=float(st.session_state.rend_fvo), step=0.5)
                st.session_state.rend_fps = st.number_input("Rendimento FPS s/ MP (%):", min_value=1.0, value=float(st.session_state.rend_fps), step=0.5)
                st.session_state.rend_oleo = st.number_input("Rendimento Óleo s/ MP (%):", min_value=1.0, value=float(st.session_state.rend_oleo), step=0.1)

        recalcular_balanco()
        vols = st.session_state.volumes_producao

        st.markdown("---")
        st.success(f"📊 **Painel de Volumes Estimados (Equivalente a {st.session_state.aves_mes_calc:,.0f} aves/mês):**")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Ração Produzida", f"{vols['Fábrica de Ração']:,.1f} ton")
        m2.metric("Matéria-Prima FFO", f"{vols['Matéria-Prima Bruta FFO']:,.1f} ton")
        m3.metric("Farinha Vísceras (FVO)", f"{vols['Farinha de Vísceras (FVO)']:,.1f} ton")
        m4.metric("Farinha Penas (FPS)", f"{vols['Farinha de Penas (FPS)']:,.1f} ton")
        m5.metric("Óleo de Frango", f"{vols['Óleo de Frango']:,.1f} ton")

    elif modulo == "2. Consulta de FT & Calculadora de Consumo (ppm)":
        st.header("Etapa 2: Portfólio de FTs & Cesta de Tratamento Multi-Ponto")

        with st.expander("🔍 Consultar Catálogo e Filtrar por Princípio Ativo (Match Direto)", expanded=True):
            cat_disp = df_produtos["Categoria"].dropna().unique().tolist() if "Categoria" in df_produtos.columns else []
            est_disp = df_produtos["Estado_Fisico"].dropna().unique().tolist() if "Estado_Fisico" in df_produtos.columns else []
            ativos_disp = extrair_lista_ativos(df_produtos)

            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                f_cat = st.multiselect("Categoria / Linha:", options=cat_disp, default=cat_disp)
            with col_f2:
                f_est = st.multiselect("Estado Físico:", options=est_disp, default=est_disp)
            with col_f3:
                f_ativos = st.multiselect("Conter Princípio(s) Ativo(s):", options=ativos_disp)

            df_ft_view = df_produtos.copy()
            if f_cat and "Categoria" in df_ft_view.columns:
                df_ft_view = df_ft_view[df_ft_view["Categoria"].isin(f_cat)]
            if f_est and "Estado_Fisico" in df_ft_view.columns:
                df_ft_view = df_ft_view[df_ft_view["Estado_Fisico"].isin(f_est)]
            if f_ativos and "Principios_Ativos_Garantias" in df_ft_view.columns:
                for atv in f_ativos:
                    df_ft_view = df_ft_view[
                        df_ft_view["Principios_Ativos_Garantias"].astype(str).str.contains(re.escape(atv), case=False, na=False)
                    ]

            st.dataframe(df_ft_view, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🛒 Cesta de Tratamento (Múltiplos Pontos de Aplicação)")
        st.markdown("Adicione ou duplique linhas para dosar múltiplos produtos na fábrica de ração ou na graxaria. A dosagem é sempre
