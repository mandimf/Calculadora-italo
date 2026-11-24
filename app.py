import hmac
import os
import re
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA E CONSTANTES
# =============================================================================
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola",
    page_icon="📊",
    layout="wide",
)

# Planilha base exclusiva (estritamente leitura - read-only)
SHEET_ID = "1JzqqiSqjuBb7GNaswi-EHKYn7SEOqt0RtYeHvt7ywj0"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv"

SINERGISTAS_NORMALIZADOS = (
    "acido citrico",
    "ácido cítrico",
    "acido fosforico",
    "ácido fosfórico",
    "edta",
)


# =============================================================================
# CAMADA DE SEGURANÇA E ACESSO A DADOS
# =============================================================================
def obter_senha_configurada() -> tuple[str, bool]:
    """Lê a senha de st.secrets ou variável de ambiente; retorna (senha, usando_secret)."""
    try:
        if "APP_PASSWORD" in st.secrets:
            return str(st.secrets["APP_PASSWORD"]), True
    except Exception:
        pass

    env_pwd = os.environ.get("APP_PASSWORD")
    if env_pwd:
        return env_pwd, True

    return "cfs2026", False


@st.cache_data(ttl=300, show_spinner="Carregando base de fichas técnicas...")
def carregar_dados_ft(url: str) -> tuple[pd.DataFrame, str]:
    """Carrega a planilha do Google Sheets em modo read-only com cache de 5 min."""
    df = pd.read_csv(url, on_bad_lines="skip")
    df.columns = [str(c).strip() for c in df.columns]
    for col in df.select_dtypes(include=["object"]).columns:
        df[col] = (
            df[col]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    timestamp = datetime.now().strftime("%H:%M:%S")
    return df, timestamp


# =============================================================================
# CAMADA DE DOMÍNIO (REGRAS DE NEGÓCIO E CÁLCULOS)
# =============================================================================
def extrair_lista_ativos(df: pd.DataFrame) -> list[str]:
    """Lista os nomes únicos de princípios ativos disponíveis para filtro."""
    if "Principios_Ativos_Garantias" not in df.columns:
        return []
    ativos_encontrados: set[str] = set()
    for texto in df["Principios_Ativos_Garantias"].dropna():
        partes = re.split(r"[|;\n]", str(texto))
        for parte in partes:
            if ":" in parte:
                nome = parte.split(":", 1)[0].strip()
                if nome:
                    ativos_encontrados.add(nome)
    return sorted(ativos_encontrados)


def analisar_ativos_e_ppm(texto_garantias: str, dosagem_g_ton: float) -> dict[str, Any]:
    """
    Analisa garantias por molécula e calcula ppm individual com precisão total.
    Trata conversão g/kg -> %, dupla declaração (sal vs. ácido / elemento vs. sal),
    sinergistas e produtos sem garantia percentual (ex.: UFC/g ou qualitativos).
    """
    resultado: dict[str, Any] = {
        "moleculas": [],
        "detalhe_ppm": "Não aplicável (%)",
        "ppm_primario_total": None,
        "tem_percentual": False,
        "aviso": "",
    }

    if not isinstance(texto_garantias, str) or not texto_garantias.strip():
        return resultado

    partes = [p.strip() for p in re.split(r"[|;\n]", texto_garantias) if p.strip()]
    moleculas_numericas: list[dict[str, Any]] = []
    nao_percentuais: list[str] = []

    padrao_valor = re.compile(
        r"(?:Mín\.?|Máx\.?)?\s*(\d+(?:[.,]\d+)?)\s*(%|g/kg)",
        re.IGNORECASE,
    )

    for parte in partes:
        if ":" in parte:
            nome, espec = [x.strip() for x in parte.split(":", 1)]
        else:
            nome, espec = "Ativo", parte

        match = padrao_valor.search(espec)
        if not match:
            nao_percentuais.append(parte)
            continue

        try:
            valor_num = float(match.group(1).replace(",", "."))
        except ValueError:
            nao_percentuais.append(parte)
            continue

        unidade = match.group(2).lower()
        pct = valor_num / 10.0 if unidade == "g/kg" else valor_num
        ppm = dosagem_g_ton * (pct / 100.0)
        nome_lower = nome.lower()
        eh_sinergista = any(s in nome_lower for s in SINERGISTAS_NORMALIZADOS)

        moleculas_numericas.append(
            {
                "nome": nome,
                "pct": pct,
                "ppm": ppm,
                "sinergista": eh_sinergista,
            }
        )

    if not moleculas_numericas:
        if nao_percentuais:
            resultado["detalhe_ppm"] = "Não aplicável (UFC/g ou qualitativo)"
        return resultado

    resultado["tem_percentual"] = True
    resultado["moleculas"] = moleculas_numericas
    resultado["detalhe_ppm"] = " | ".join(
        f"{m['nome']}: {m['ppm']:,.1f} ppm" for m in moleculas_numericas
    )

    nomes_lower = [m["nome"].lower() for m in moleculas_numericas]
    tem_prop_ca = any("propionato de cálcio" in n or "propionato de calcio" in n for n in nomes_lower)
    tem_ac_prop = any("ácido propiônico" in n or "acido propionico" in n for n in nomes_lower)
    tem_cromo_total = any("cromo total" in n for n in nomes_lower)
    tem_prop_cromo = any("propionato de cromo" in n for n in nomes_lower)

    avisos: list[str] = []
    ppm_primario = 0.0

    for m in moleculas_numericas:
        nome_l = m["nome"].lower()
        if m["sinergista"]:
            continue
        if tem_prop_ca and tem_ac_prop and ("propionato de cálcio" in nome_l or "propionato de calcio" in nome_l):
            avisos.append("Dupla declaração (Propionato/Propiônico): total considera Ácido Propiônico.")
            continue
        if tem_cromo_total and tem_prop_cromo and "propionato de cromo" in nome_l:
            avisos.append("Dupla declaração (Cromo): total considera Cromo Total elementar.")
            continue
        ppm_primario += m["ppm"]

    # Se todos os itens numéricos forem sinergistas (ex.: produto só de ácido cítrico/fosfórico)
    if ppm_primario == 0.0 and moleculas_numericas:
        ppm_primario = sum(m["ppm"] for m in moleculas_numericas)

    resultado["ppm_primario_total"] = ppm_primario
    resultado["aviso"] = " ".join(avisos)
    return resultado


def ordenar_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena portfólio priorizando Xtendra, Novamold, Salplus e Dresbond."""
    if df.empty:
        return df

    def peso_ordem(row: pd.Series) -> int:
        texto = f"{row.get('Marca_Linha', '')} {row.get('Categoria', '')} {row.get('Produto', '')}".lower()
        if any(k in texto for k in ("xtendra", "anox", "nasure")):
            return 1
        if any(k in texto for k in ("novamold", "propical")):
            return 2
        if "salplus" in texto:
            return 3
        if "dresbond" in texto:
            return 4
        return 5

    df_copia = df.copy()
    df_copia["_ordem"] = df_copia.apply(peso_ordem, axis=1)
    sort_cols = ["_ordem", "Produto"] if "Produto" in df_copia.columns else ["_ordem"]
    return df_copia.sort_values(by=sort_cols).drop(columns=["_ordem"])


def calcular_balanco_massa(
    tipo_gatilho: str,
    aves_dia: float,
    dias_mes: int,
    racao_input: float,
    mp_input: float,
    consumo_ave: float,
    peso_ave: float,
    rend_mp_pv: float,
    rend_fvo: float,
    rend_fps: float,
    rend_oleo: float,
) -> tuple[float, dict[str, float]]:
    """Calcula aves/mês e volumes industriais mantendo precisão total."""
    if tipo_gatilho == "Aves Abatidas":
        aves_mes = aves_dia * dias_mes
        racao_calc = (aves_mes * consumo_ave) / 1000.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    elif tipo_gatilho == "Produção de Ração":
        racao_calc = racao_input
        aves_mes = (racao_calc * 1000.0) / consumo_ave if consumo_ave > 0 else 0.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    else:
        mp_calc = mp_input
        fator_mp = peso_ave * (rend_mp_pv / 100.0)
        aves_mes = (mp_calc * 1000.0) / fator_mp if fator_mp > 0 else 0.0
        racao_calc = (aves_mes * consumo_ave) / 1000.0

    volumes = {
        "Fábrica de Ração": racao_calc,
        "Matéria-Prima Bruta FFO": mp_calc,
        "Farinha de Vísceras (FVO)": mp_calc * (rend_fvo / 100.0),
        "Farinha de Penas (FPS)": mp_calc * (rend_fps / 100.0),
        "Óleo de Frango": mp_calc * (rend_oleo / 100.0),
    }
    return aves_mes, volumes


# =============================================================================
# GESTÃO DE ESTADO (SESSION STATE)
# =============================================================================
def inicializar_sessao(lista_produtos: list[str]) -> None:
    defaults: dict[str, Any] = {
        "cliente_nome": "",
        "cliente_cnpj": "",
        "cliente_contato": "",
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
        "next_id": 3,
        "crm_historico": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    prod_inicial = lista_produtos[0] if lista_produtos else ""
    if "cesta_aplicacao" not in st.session_state:
        st.session_state.cesta_aplicacao = [
            {
                "id": 1,
                "matriz": "Farinha de Vísceras (FVO)",
                "produto": prod_inicial,
                "dosagem": 500.0,
                "observacao": "Aplicação primária no fluxo",
                "preco_kg": 15.0,
                "share": 100,
            },
            {
                "id": 2,
                "matriz": "Óleo de Frango",
                "produto": prod_inicial,
                "dosagem": 1000.0,
                "observacao": "Estabilização lipídica",
                "preco_kg": 18.0,
                "share": 100,
            },
        ]


def atualizar_balanco_sessao() -> None:
    aves_mes, volumes = calcular_balanco_massa(
        tipo_gatilho=st.session_state.tipo_gatilho,
        aves_dia=st.session_state.aves_dia,
        dias_mes=st.session_state.dias_mes,
        racao_input=st.session_state.racao_input,
        mp_input=st.session_state.mp_input,
        consumo_ave=st.session_state.consumo_ave,
        peso_ave=st.session_state.peso_ave,
        rend_mp_pv=st.session_state.rend_mp_pv,
        rend_fvo=st.session_state.rend_fvo,
        rend_fps=st.session_state.rend_fps,
        rend_oleo=st.session_state.rend_oleo,
    )
    st.session_state.aves_mes_calc = aves_mes
    st.session_state.volumes_producao = volumes


# =============================================================================
# CAMADA DE APRESENTAÇÃO (STREAMLIT UI)
# =============================================================================
def renderizar_login() -> bool:
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if st.session_state.autenticado:
        return True

    senha_correta, _ = obter_senha_configurada()

    st.title("🔒 Autenticação Restrita")
    st.markdown("Insira a senha de acesso para utilizar o Ecossistema Comercial.")

    with st.form("form_login"):
        senha_digitada = st.text_input("Senha de Acesso:", type="password")
        enviado = st.form_submit_button("Entrar", type="primary")
        if enviado:
            if hmac.compare_digest(senha_digitada, senha_correta):
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Senha incorreta. Tente novamente.")
    return False


def main() -> None:
    if not renderizar_login():
        return

    _, usando_secret = obter_senha_configurada()

    st.title("🐔 Ecossistema Comercial - Nutrição Avícola & Graxaria (US$)")
    st.markdown(
        "Suporte técnico-comercial integrado: Cadastro de Cliente, Balanço de Massa, "
        "Cesta Multi-Ponto (ppm por molécula) e Faturamento em Dólar."
    )

    try:
        df_bruto, hora_carga = carregar_dados_ft(SHEET_URL)
    except Exception as exc:
        st.error(
            f"Não foi possível carregar a planilha do Google Sheets. "
            f"Verifique a conexão ou as permissões de leitura pública. Detalhe: {exc}"
        )
        return

    if df_bruto.empty or "Produto" not in df_bruto.columns:
        st.warning(
            "A base de dados retornou vazia ou sem a coluna obrigatória 'Produto'. "
            "Verifique a estrutura da planilha base."
        )
        return

    df_produtos = ordenar_portfolio(df_bruto)
    lista_produtos = [p for p in df_produtos["Produto"].tolist() if p]

    inicializar_sessao(lista_produtos)
    atualizar_balanco_sessao()

    # Sidebar: status, atualização manual e navegação
    st.sidebar.success(f"Base conectada: {len(df_produtos)} produtos")
    st.sidebar.caption(f"Última sincronização: {hora_carga} (cache 5 min)")
    if st.sidebar.button("🔄 Atualizar Base", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if not usando_secret:
        st.sidebar.info(
            "Dica de segurança: configure `APP_PASSWORD` em Streamlit Secrets "
            "para não depender da senha padrão no código."
        )

    st.sidebar.markdown("---")
    st.sidebar.header("🧭 Navegação")
    modulo = st.sidebar.radio(
        "Selecione a Etapa:",
        [
            "0. Cadastro do Cliente & CRM",
            "1. Balanço de Massa & Produção",
            "2. Consulta de FT & Cesta de Tratamento",
            "3. Simulação de Faturamento & Relatório Executivo (US$)",
        ],
    )

    # -------------------------------------------------------------------------
    # MÓDULO 0: CADASTRO DO CLIENTE & CRM
    # -------------------------------------------------------------------------
    if modulo == "0. Cadastro do Cliente & CRM":
        st.header("Etapa 0: Identificação e Histórico do Cliente (Base CRM)")
        st.markdown("Cadastre os dados da conta para associar às simulações.")

        c_col1, c_col2 = st.columns(2)
        with c_col1:
            st.session_state.cliente_nome = st.text_input(
                "Nome da Empresa / Cliente:",
                value=st.session_state.cliente_nome,
                placeholder="Ex.: Integração Avícola XYZ",
            )
            st.session_state.cliente_cnpj = st.text_input(
                "CNPJ:",
                value=st.session_state.cliente_cnpj,
                placeholder="00.000.000/0001-00",
            )
        with c_col2:
            st.session_state.cliente_contato = st.text_input(
                "Responsável / Contato Técnico-Comercial:",
                value=st.session_state.cliente_contato,
                placeholder="Ex.: João Silva (Nutricionista)",
            )

        st.markdown("---")
        st.subheader("🗂️ Histórico de Simulações Salvas na Sessão")
        if st.button("💾 Salvar Simulação Atual no CRM", type="primary"):
            if not st.session_state.cliente_nome.strip():
                st.warning("Preencha o Nome da Empresa antes de salvar.")
            else:
                reg = {
                    "Data/Hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "Cliente": st.session_state.cliente_nome.strip(),
                    "CNPJ": st.session_state.cliente_cnpj.strip() or "N/A",
                    "Contato": st.session_state.cliente_contato.strip() or "N/A",
                    "Abate (aves/dia)": (
                        st.session_state.aves_dia
                        if st.session_state.tipo_gatilho == "Aves Abatidas"
                        else "N/A"
                    ),
                    "Ração (ton/mês)": round(
                        st.session_state.volumes_producao["Fábrica de Ração"], 1
                    ),
                    "Itens na Cesta": len(st.session_state.cesta_aplicacao),
                }
                st.session_state.crm_historico.append(reg)
                st.success(f"Simulação para '{reg['Cliente']}' salva no histórico da sessão.")

        if st.session_state.crm_historico:
            st.dataframe(
                pd.DataFrame(st.session_state.crm_historico),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("Nenhuma simulação salva nesta sessão ainda.")

    # -------------------------------------------------------------------------
    # MÓDULO 1: BALANÇO DE MASSA & PRODUÇÃO
    # -------------------------------------------------------------------------
    elif modulo == "1. Balanço de Massa & Produção":
        st.header("Etapa 1: Simulador de Produção e Balanço de Massa")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome}")

        opcoes_gatilho = [
            "Aves Abatidas",
            "Produção de Ração",
            "Matéria-Prima FFO Recebida",
        ]
        st.session_state.tipo_gatilho = st.radio(
            "Qual dado de partida você tem?",
            opcoes_gatilho,
            index=opcoes_gatilho.index(st.session_state.tipo_gatilho),
            horizontal=True,
        )

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("🎯 Entrada do Gatilho Principal")
            if st.session_state.tipo_gatilho == "Aves Abatidas":
                st.session_state.aves_dia = st.number_input(
                    "Abate Diário (aves/dia):",
                    min_value=1.0,
                    value=float(st.session_state.aves_dia),
                    step=5000.0,
                )
                st.session_state.dias_mes = st.number_input(
                    "Dias de Operação / Mês:",
                    min_value=1,
                    max_value=31,
                    value=int(st.session_state.dias_mes),
                    step=1,
                )
            elif st.session_state.tipo_gatilho == "Produção de Ração":
                st.session_state.racao_input = st.number_input(
                    "Volume de Ração Produzida (ton/mês):",
                    min_value=1.0,
                    value=float(st.session_state.racao_input),
                    step=500.0,
                )
            else:
                st.session_state.mp_input = st.number_input(
                    "Matéria-Prima Bruta Recebida na FFO (ton/mês):",
                    min_value=1.0,
                    value=float(st.session_state.mp_input),
                    step=250.0,
                )

        with col2:
            st.subheader("⚙️ Índices Zootécnicos e Industriais")
            p_c1, p_c2 = st.columns(2)
            with p_c1:
                st.session_state.consumo_ave = st.number_input(
                    "Consumo Ração/Ave (kg):",
                    min_value=0.1,
                    value=float(st.session_state.consumo_ave),
                    step=0.1,
                )
                st.session_state.peso_ave = st.number_input(
                    "Peso Vivo Médio (kg):",
                    min_value=0.1,
                    value=float(st.session_state.peso_ave),
                    step=0.1,
                )
                st.session_state.rend_mp_pv = st.number_input(
                    "Rendimento MP s/ PV (%):",
                    min_value=1.0,
                    max_value=100.0,
                    value=float(st.session_state.rend_mp_pv),
                    step=0.5,
                )
            with p_c2:
                st.session_state.rend_fvo = st.number_input(
                    "Rendimento FVO s/ MP (%):",
                    min_value=1.0,
                    max_value=100.0,
                    value=float(st.session_state.rend_fvo),
                    step=0.5,
                )
                st.session_state.rend_fps = st.number_input(
                    "Rendimento FPS s/ MP (%):",
                    min_value=1.0,
                    max_value=100.0,
                    value=float(st.session_state.rend_fps),
                    step=0.5,
                )
                st.session_state.rend_oleo = st.number_input(
                    "Rendimento Óleo s/ MP (%):",
                    min_value=1.0,
                    max_value=100.0,
                    value=float(st.session_state.rend_oleo),
                    step=0.1,
                )

        atualizar_balanco_sessao()
        vols = st.session_state.volumes_producao

        st.markdown("---")
        st.success(
            f"📊 **Painel de Volumes Estimados (Equivalente a "
            f"{st.session_state.aves_mes_calc:,.0f} aves/mês):**"
        )
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Ração Produzida", f"{vols['Fábrica de Ração']:,.1f} ton")
        m2.metric("Matéria-Prima FFO", f"{vols['Matéria-Prima Bruta FFO']:,.1f} ton")
        m3.metric("Farinha Vísceras (FVO)", f"{vols['Farinha de Vísceras (FVO)']:,.1f} ton")
        m4.metric("Farinha Penas (FPS)", f"{vols['Farinha de Penas (FPS)']:,.1f} ton")
        m5.metric("Óleo de Frango", f"{vols['Óleo de Frango']:,.1f} ton")

    # -------------------------------------------------------------------------
    # MÓDULO 2: CONSULTA DE FT & CESTA DE TRATAMENTO
    # -------------------------------------------------------------------------
    elif modulo == "2. Consulta de FT & Cesta de Tratamento":
        st.header("Etapa 2: Portfólio de FTs & Cesta de Tratamento Multi-Ponto")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome}")

        with st.expander("🔍 Consultar Catálogo e Filtrar por Princípio Ativo", expanded=False):
            cat_disp = (
                sorted([c for c in df_produtos["Categoria"].unique().tolist() if c])
                if "Categoria" in df_produtos.columns
                else []
            )
            est_disp = (
                sorted([e for e in df_produtos["Estado_Fisico"].unique().tolist() if e])
                if "Estado_Fisico" in df_produtos.columns
                else []
            )
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
                        df_ft_view["Principios_Ativos_Garantias"]
                        .astype(str)
                        .str.contains(re.escape(atv), case=False, na=False)
                    ]

            if df_ft_view.empty:
                st.info("Nenhum produto encontrado para a combinação de filtros selecionada.")
            else:
                st.dataframe(df_ft_view, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🛒 Cesta de Tratamento (Múltiplos Pontos de Aplicação)")
        st.markdown("Adicione ou duplique linhas para dosar múltiplos produtos. A dosagem é sempre em **g/ton**.")

        matrizes_opcoes = st.session_state.volumes_producao
        lista_mat = list(matrizes_opcoes.keys())
        itens_para_remover: list[int] = []
        itens_para_duplicar: list[dict[str, Any]] = []
        resumo_cesta: list[dict[str, Any]] = []

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            c1, c2, c3, c4, c5, c6 = st.columns([2.2, 2.8, 1.5, 2.5, 1.0, 0.6])

            with c1:
                mat_idx = lista_mat.index(item["matriz"]) if item["matriz"] in lista_mat else 0
                item["matriz"] = st.selectbox(
                    f"Matriz #{idx + 1}:",
                    options=lista_mat,
                    index=mat_idx,
                    key=f"matriz_{item['id']}",
                )
            with c2:
                prod_idx = lista_produtos.index(item["produto"]) if item["produto"] in lista_produtos else 0
                item["produto"] = st.selectbox(
                    f"Produto #{idx + 1}:",
                    options=lista_produtos,
                    index=prod_idx,
                    key=f"prod_{item['id']}",
                )
            with c3:
                item["dosagem"] = st.number_input(
                    f"g/ton #{idx + 1}:",
                    min_value=0.0,
                    value=float(item["dosagem"]),
                    step=50.0,
                    key=f"dose_{item['id']}",
                )
            with c4:
                item["observacao"] = st.text_input(
                    f"Observação #{idx + 1}:",
                    value=str(item.get("observacao", "")),
                    placeholder="Ex.: Bico pós-peletização",
                    key=f"obs_{item['id']}",
                )
            with c5:
                st.write("")
                st.write("")
                if st.button("➕ Dup", key=f"dup_{item['id']}", use_container_width=True):
                    itens_para_duplicar.append(item.copy())
            with c6:
                st.write("")
                st.write("")
                if len(st.session_state.cesta_aplicacao) > 1:
                    if st.button("🗑️", key=f"del_{item['id']}", use_container_width=True):
                        itens_para_remover.append(item["id"])

            vol_base = matrizes_opcoes.get(item["matriz"], 0.0)
            consumo_linha_kg = (vol_base * item["dosagem"]) / 1000.0

            linhas_prod = df_produtos[df_produtos["Produto"] == item["produto"]]
            info_p = linhas_prod.iloc[0] if not linhas_prod.empty else None
            garantia_str = (
                str(info_p["Principios_Ativos_Garantias"])
                if info_p is not None and "Principios_Ativos_Garantias" in df_produtos.columns
                else ""
            )
            comp_str = (
                str(info_p["Composicao"])
                if info_p is not None and "Composicao" in df_produtos.columns
                else ""
            )
            est_fisico = (
                str(info_p["Estado_Fisico"])
                if info_p is not None and "Estado_Fisico" in df_produtos.columns
                else ""
            )

            analise_ppm = analisar_ativos_e_ppm(garantia_str, float(item["dosagem"]))
            ppm_primario_exib = (
                f"{analise_ppm['ppm_primario_total']:,.1f} ppm"
                if analise_ppm["ppm_primario_total"] is not None
                else "N/A"
            )

            st.caption(
                f"📌 **{item['produto']} ({est_fisico})** | **Entrega por Molécula:** {analise_ppm['detalhe_ppm']} | "
                f"**Consumo:** {consumo_linha_kg:,.1f} kg/mês *(em {vol_base:,.1f} ton)*"
            )
            if comp_str:
                st.caption(f"🧪 **Composição:** {comp_str}")
            if analise_ppm["aviso"]:
                st.caption(f"ℹ️ {analise_ppm['aviso']}")
            st.markdown("---")

            resumo_cesta.append(
                {
                    "Ponto": idx + 1,
                    "Matriz Aplicada": item["matriz"],
                    "Volume Matriz (ton/mês)": round(vol_base, 1),
                    "Produto Comercial": item["produto"],
                    "Estado Físico": est_fisico,
                    "Dosagem (g/ton)": round(item["dosagem"], 1),
                    "Entrega por Molécula (ppm)": analise_ppm["detalhe_ppm"],
                    "Total Ativo Primário": ppm_primario_exib,
                    "Observação": item["observacao"],
                    "Consumo Mensal (kg)": round(consumo_linha_kg, 2),
                }
            )

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
            st.session_state.cesta_aplicacao.append(
                {
                    "id": st.session_state.next_id,
                    "matriz": "Fábrica de Ração",
                    "produto": lista_produtos[0] if lista_produtos else "",
                    "dosagem": 500.0,
                    "observacao": "",
                    "preco_kg": 15.0,
                    "share": 100,
                }
            )
            st.session_state.next_id += 1
            st.rerun()

        df_resumo = pd.DataFrame(resumo_cesta)
        st.subheader("📋 Quadro Consolidado de Consumo e Entrega por Molécula")
        st.dataframe(df_resumo, use_container_width=True, hide_index=True)

        total_kg_geral = float(df_resumo["Consumo Mensal (kg)"].sum()) if not df_resumo.empty else 0.0
        st.success(f"📦 **Volume Físico Total Estimado na Conta:** {total_kg_geral:,.2f} kg / mês")

    # -------------------------------------------------------------------------
    # MÓDULO 3: SIMULAÇÃO DE FATURAMENTO & RELATÓRIO EXECUTIVO (US$)
    # -------------------------------------------------------------------------
    elif modulo == "3. Simulação de Faturamento & Relatório Executivo (US$)":
        st.header("Etapa 3: Simulador de Faturamento, Custo por Tonelada e Proposta Comercial (US$)")
        if st.session_state.cliente_nome:
            st.info(
                f"👤 **Cliente Ativo:** {st.session_state.cliente_nome} "
                f"(CNPJ: {st.session_state.cliente_cnpj or 'N/A'})"
            )

        matrizes_opcoes = st.session_state.volumes_producao
        linhas_financeiro: list[dict[str, Any]] = []

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            vol_base = matrizes_opcoes.get(item["matriz"], 0.0)
            consumo_kg_100 = (vol_base * item["dosagem"]) / 1000.0

            linhas_prod = df_produtos[df_produtos["Produto"] == item["produto"]]
            info_p = linhas_prod.iloc[0] if not linhas_prod.empty else None
            garantia_str = (
                str(info_p["Principios_Ativos_Garantias"])
                if info_p is not None and "Principios_Ativos_Garantias" in df_produtos.columns
                else ""
            )
            analise_ppm = analisar_ativos_e_ppm(garantia_str, float(item["dosagem"]))

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(f"**{idx + 1}. {item['produto']}** *(em {item['matriz']})*")
                st.caption(
                    f"Dosagem: {item['dosagem']:,.0f} g/ton | {analise_ppm['detalhe_ppm']} | "
                    f"Obs: {item.get('observacao') or 'N/A'}"
                )
            with c_fin2:
                item["preco_kg"] = st.number_input(
                    f"Preço US$/kg (#{idx + 1}):",
                    min_value=0.0,
                    value=float(item.get("preco_kg", 15.0)),
                    step=0.5,
                    key=f"preco_{item['id']}",
                )
            with c_fin3:
                item["share"] = st.slider(
                    f"Share % (#{idx + 1}):",
                    min_value=10,
                    max_value=100,
                    value=int(item.get("share", 100)),
                    step=10,
                    key=f"share_{item['id']}",
                )

            consumo_real_kg = consumo_kg_100 * (item["share"] / 100.0)
            faturamento_item = consumo_real_kg * item["preco_kg"]
            custo_ton_tratada = (item["dosagem"] / 1000.0) * item["preco_kg"]

            with c_fin4:
                st.metric(
                    label=f"Faturamento Item #{idx + 1}",
                    value=f"US$ {faturamento_item:,.2f} /mês",
                    delta=f"Custo Tratamento: US$ {custo_ton_tratada:,.2f} /ton",
                )
            st.markdown("---")

            linhas_financeiro.append(
                {
                    "Matriz": item["matriz"],
                    "Produto": item["produto"],
                    "Dosagem (g/ton)": round(float(item["dosagem"]), 1),
                    "Entrega (ppm)": analise_ppm["detalhe_ppm"],
                    "Observação": item.get("observacao", ""),
                    "Custo Tratamento (US$/ton)": round(custo_ton_tratada, 2),
                    "Share (%)": item["share"],
                    "Volume Faturado (kg/mês)": round(consumo_real_kg, 2),
                    "Preço Unitário (US$/kg)": round(float(item["preco_kg"]), 2),
                    "Faturamento Mensal (US$)": round(faturamento_item, 2),
                    "Faturamento Anual (US$)": round(faturamento_item * 12.0, 2),
                }
            )

        df_fin = pd.DataFrame(linhas_financeiro)
        st.subheader("💼 Resumo Executivo da Conta (US$)")
        st.dataframe(df_fin, use_container_width=True, hide_index=True)

        fat_mensal_total = float(df_fin["Faturamento Mensal (US$)"].sum()) if not df_fin.empty else 0.0
        fat_anual_total = float(df_fin["Faturamento Anual (US$)"].sum()) if not df_fin.empty else 0.0
        vol_faturado_total = float(df_fin["Volume Faturado (kg/mês)"].sum()) if not df_fin.empty else 0.0

        r1, r2, r3 = st.columns(3)
        r1.metric("Volume Total Faturado (com Share)", f"{vol_faturado_total:,.1f} kg/mês")
        r2.metric("Faturamento Mensal Consolidado", f"US$ {fat_mensal_total:,.2f}")
        r3.metric("Potencial Anualizado da Conta", f"US$ {fat_anual_total:,.2f}")

        st.markdown("---")
        st.subheader("📄 Relatório Executivo / Proposta Comercial para Cliente")
        if st.button("Gerar Proposta Comercial Textual", type="primary"):
            st.markdown("### **PROPOSTA COMERCIAL - SOLUÇÕES EM NUTRIÇÃO ANIMAL**")
            st.markdown("---")
            st.markdown(f"**Cliente:** {st.session_state.cliente_nome or 'Não especificado'}")
            st.markdown(f"**CNPJ:** {st.session_state.cliente_cnpj or 'N/A'}")
            st.markdown(f"**Contato Responsável:** {st.session_state.cliente_contato or 'N/A'}")
            st.markdown("#### **Resumo da Cesta de Tratamento e Investimento:**")

            for lf in linhas_financeiro:
                obs_txt = lf["Observação"] or "Sem observações"
                st.markdown(
                    f"- **Produto:** {lf['Produto']} ({lf['Matriz']}) | "
                    f"**Dosagem:** {lf['Dosagem (g/ton)']} g/ton | "
                    f"**Ativos:** {lf['Entrega (ppm)']} | "
                    f"**Custo/ton:** US$ {lf['Custo Tratamento (US$/ton)']:,.2f} | "
                    f"**Obs:** {obs_txt} | "
                    f"**Preço:** US$ {lf['Preço Unitário (US$/kg)']:,.2f}/kg | "
                    f"**Faturamento Mensal:** US$ {lf['Faturamento Mensal (US$)']:,.2f}"
                )

            st.markdown("---")
            st.markdown(f"* **Faturamento Mensal Total Estimado:** **US$ {fat_mensal_total:,.2f}**")
            st.markdown(f"* **Potencial Anualizado:** **US$ {fat_anual_total:,.2f}**")


if __name__ == "__main__":
    main()
