import re
import pandas as pd
import streamlit as st

# Configuração da Página
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide"
)

# ID da Planilha Base Exclusiva Fornecida pelo Usuário
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
        st.warning("A base de dados retornou vazia ou inacessível. Verifique o compartilhamento da planilha base.")
        return

    df_produtos = ordenar_portfolio(df_bruto)
    lista_produtos = df_produtos["Produto"].dropna().tolist() if "Produto" in df_produtos.columns else []

    inicializar_sessao(lista_produtos)
    recalcular_balanco()

    st.sidebar.success(f"Base de dados conectada: {len(df_produtos)} produtos")
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
        st.markdown("Adicione ou duplique linhas para dosar múltiplos produtos na fábrica de ração ou na graxaria. A dosagem é sempre em **g/ton**.")

        matrizes_opcoes = st.session_state.volumes_producao
        itens_para_remover = []
        itens_para_duplicar = []
        resumo_cesta = []

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            c1, c2, c3, c4, c5 = st.columns([2.5, 3.5, 2, 1.2, 0.8])

            with c1:
                lista_mat = list(matrizes_opcoes.keys())
                mat_idx = lista_mat.index(item["matriz"]) if item["matriz"] in lista_mat else 0
                item["matriz"] = st.selectbox(f"Matriz #{idx + 1}:", options=lista_mat, index=mat_idx, key=f"matriz_{item['id']}")
            with c2:
                prod_idx = lista_produtos.index(item["produto"]) if item["produto"] in lista_produtos else 0
                item["produto"] = st.selectbox(f"Produto Comercial #{idx + 1}:", options=lista_produtos, index=prod_idx, key=f"prod_{item['id']}")
            with c3:
                item["dosagem"] = st.number_input(f"Dosagem (g/ton) #{idx + 1}:", min_value=0.0, value=float(item["dosagem"]), step=50.0, key=f"dose_{item['id']}")
            with c4:
                st.write("")
                st.write("")
                if st.button("➕ Duplicar", key=f"dup_{item['id']}", use_container_width=True):
                    itens_para_duplicar.append(item.copy())
            with c5:
                st.write("")
                st.write("")
                if len(st.session_state.cesta_aplicacao) > 1:
                    if st.button("🗑️", key=f"del_{item['id']}", use_container_width=True):
                        itens_para_remover.append(item["id"])

            vol_base = matrizes_opcoes.get(item["matriz"], 0.0)
            consumo_linha_kg = (vol_base * item["dosagem"]) / 1000.0

            info_p = df_produtos[df_produtos["Produto"] == item["produto"]].iloc[0] if item["produto"] in lista_produtos else None
            garantia_str = str(info_p["Principios_Ativos_Garantias"]) if info_p is not None and "Principios_Ativos_Garantias" in df_produtos.columns else ""
            comp_str = str(info_p["Composicao"]) if info_p is not None and "Composicao" in df_produtos.columns else ""
            est_fisico = str(info_p["Estado_Fisico"]) if info_p is not None and "Estado_Fisico" in df_produtos.columns else ""

            soma_ativos = extrair_soma_ativos_pct(garantia_str)
            ppm_linha = item["dosagem"] * (soma_ativos / 100.0)

            st.caption(f"📌 **{item['produto']} ({est_fisico})** | **Garantias:** {garantia_str} | **Composição:** {comp_str} ➡️ **Ativo Entregue: {ppm_linha:,.1f} ppm** *(Consumo: {consumo_linha_kg:,.1f} kg/mês p/ {vol_base:,.1f} ton)*")
            st.markdown("---")

            resumo_cesta.append({
                "Ponto": idx + 1,
                "Matriz Aplicada": item["matriz"],
                "Volume Matriz (ton/mês)": round(vol_base, 1),
                "Produto Comercial": item["produto"],
                "Estado Físico": est_fisico,
                "Dosagem (g/ton)": round(item["dosagem"], 1),
                "Ativos Declarados (%)": round(soma_ativos, 2),
                "Ativo Dosado (ppm)": round(ppm_linha, 1) if soma_ativos > 0 else 0.0,
                "Consumo Mensal (kg)": round(consumo_linha_kg, 2)
            })

        if itens_para_duplicar:
            for it in itens_para_duplicar:
                novo_item = it.copy()
                novo_item["id"] = st.session_state.next_id
                st.session_state.cesta_aplicacao.append(novo_item)
                st.session_state.next_id += 1
            st.rerun()

        if itens_para_remover:
            st.session_state.cesta_aplicacao = [
                it for it in st.session_state.cesta_aplicacao if it["id"] not in itens_para_remover
            ]
            st.rerun()

        if st.button("➕ Adicionar Nova Linha de Tratamento"):
            st.session_state.cesta_aplicacao.append({
                "id": st.session_state.next_id,
                "matriz": "Fábrica de Ração",
                "produto": lista_produtos[0] if lista_produtos else None,
                "dosagem": 500.0,
                "preco_kg": 35.0,
                "share": 100
            })
            st.session_state.next_id += 1
            st.rerun()

        df_resumo = pd.DataFrame(resumo_cesta)
        st.subheader("📋 Quadro Consolidado de Consumo e Entrega em ppm")
        st.dataframe(df_resumo, use_container_width=True, hide_index=True)

        total_kg_geral = df_resumo["Consumo Mensal (kg)"].sum() if not df_resumo.empty else 0.0
        st.success(f"📦 **Volume Físico Total Estimado na Conta:** {total_kg_geral:,.2f} kg / mês")

    elif modulo == "3. Simulação de Faturamento & Fechamento":
        st.header("Etapa 3: Simulador de Faturamento e Custo por Tonelada Tratada")
        st.markdown("Defina o preço praticado (R$/kg) e o share pretendido para cada item configurado na Cesta de Tratamento.")

        matrizes_opcoes = st.session_state.volumes_producao
        linhas_financeiro = []

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            vol_base = matrizes_opcoes.get(item["matriz"], 0.0)
            consumo_kg_100 = (vol_base * item["dosagem"]) / 1000.0

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(f"**{idx + 1}. {item['produto']}** *(em {item['matriz']})*")
                st.caption(f"Dosagem: {item['dosagem']:,.0f} g/ton | Demanda 100%: {consumo_kg_100:,.1f} kg/mês")
            with c_fin2:
                item["preco_kg"] = st.number_input(f"Preço R$/kg (#{idx + 1}):", min_value=0.0, value=float(item.get("preco_kg", 35.0)), step=1.0, key=f"preco_{item['id']}")
            with c_fin3:
                item["share"] = st.slider(f"Share % (#{idx + 1}):", min_value=10, max_value=100, value=int(item.get("share", 100)), step=10, key=f"share_{item['id']}")

            consumo_real_kg = consumo_kg_100 * (item["share"] / 100.0)
            faturamento_item = consumo_real_kg * item["preco_kg"]
            custo_ton_tratada = (item["dosagem"] / 1000.0) * item["preco_kg"]

            with c_fin4:
                st.metric(
                    label=f"Faturamento Item #{idx + 1}",
                    value=f"R$ {faturamento_item:,.2f} /mês",
                    delta=f"Custo Tratamento: R$ {custo_ton_tratada:,.2f} /ton"
                )
            st.markdown("---")

            linhas_financeiro.append({
                "Matriz": item["matriz"],
                "Produto": item["produto"],
                "Dosagem (g/ton)": item["dosagem"],
                "Custo Tratamento (R$/ton)": round(custo_ton_tratada, 2),
                "Share (%)": item["share"],
                "Volume Faturado (kg/mês)": round(consumo_real_kg, 2),
                "Preço Unitário (R$/kg)": round(item["preco_kg"], 2),
                "Faturamento Mensal (R$)": round(faturamento_item, 2),
                "Faturamento Anual (R$)": round(faturamento_item * 12.0, 2)
            })

        df_fin = pd.DataFrame(linhas_financeiro)
        st.subheader("💼 Resumo Executivo da Conta")
        st.dataframe(df_fin, use_container_width=True, hide_index=True)

        fat_mensal_total = df_fin["Faturamento Mensal (R$)"].sum() if not df_fin.empty else 0.0
        fat_anual_total = df_fin["Faturamento Anual (R$)"].sum() if not df_fin.empty else 0.0
        vol_faturado_total = df_fin["Volume Faturado (kg/mês)"].sum() if not df_fin.empty else 0.0

        r1, r2, r3 = st.columns(3)
        r1.metric("Volume Total Faturado (com Share)", f"{vol_faturado_total:,.1f} kg/mês")
        r2.metric("Faturamento Mensal Consolidado", f"R$ {fat_mensal_total:,.2f}")
        r3.metric("Potencial Anualizado da Conta", f"R$ {fat_anual_total:,.2f}")


if __name__ == "__main__":
    main()
