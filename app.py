import hmac
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import streamlit as st

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA E CONSTANTES
# =============================================================================
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola & Graxaria",
    page_icon="📊",
    layout="wide",
)

ABA_PRODUTOS = "Produtos"
ABA_GARANTIAS = "Garantias_Ativos"

COLUNAS_PRODUTOS = [
    "id_produto",
    "categoria",
    "linha",
    "produto",
    "estado_fisico",
    "limite_regulatorio",
    "composicao",
    "ft_revisao",
    "ft_data",
]

COLUNAS_GARANTIAS = [
    "id_produto",
    "produto",
    "ativo_padronizado",
    "operador",
    "valor_numerico",
    "unidade",
]

# Pares de dupla declaração: (ativo_a_excluir_da_soma, ativo_principal_mantido)
# Evita somar sal + ácido equivalente ou polímero + nitrogênio analítico no total de ppm.
PARES_DUPLA_DECLARACAO: List[Tuple[str, str]] = [
    ("Propionato de Cálcio", "Ácido Propiônico"),
    ("Formiato de Cálcio", "Ácido Fórmico"),
    ("Nitrogênio Total", "Polimetilcarbamida"),
]

SINERGISTAS = {"Ácido Cítrico", "Ácido Fosfórico", "EDTA"}


# =============================================================================
# CAMADA DE ACESSO A DADOS (READ-ONLY GOOGLE SHEETS)
# =============================================================================
def extrair_sheet_id(valor: str) -> str:
    """Aceita tanto o ID puro quanto a URL completa da planilha no Google Sheets."""
    texto = valor.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", texto)
    return match.group(1) if match else texto


def obter_sheet_id_secrets() -> str:
    """Lê SHEET_ID (ou URL da planilha) de st.secrets, se configurado."""
    try:
        bruto = str(st.secrets.get("SHEET_ID", "")).strip()
        return extrair_sheet_id(bruto)
    except Exception:
        return ""


def obter_senha_app() -> str:
    """Lê APP_PASSWORD de st.secrets, com fallback temporário para transição."""
    try:
        return str(st.secrets.get("APP_PASSWORD", "cfs2026"))
    except Exception:
        return "cfs2026"


def montar_url_csv(sheet_id: str, nome_aba: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={quote(nome_aba)}"
    )


def _limpar_colunas_texto(df: pd.DataFrame) -> pd.DataFrame:
    df_limpo = df.copy()
    df_limpo.columns = [str(c).strip() for c in df_limpo.columns]
    for col in df_limpo.select_dtypes(include=["object"]).columns:
        df_limpo[col] = (
            df_limpo[col]
            .fillna("")
            .astype(str)
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
        )
    return df_limpo


@st.cache_data(ttl=300, show_spinner="Sincronizando base de consulta (2 abas)...")
def carregar_base_normalizada(
    sheet_id: str,
) -> Tuple[pd.DataFrame, pd.DataFrame, str, Optional[str]]:
    """
    Lê as abas 'Produtos' e 'Garantias_Ativos' em modo somente leitura (read-only).
    Retorna: (df_produtos, df_garantias, horario_sync, mensagem_erro)
    """
    horario_sync = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    if not sheet_id:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            horario_sync,
            "Informe o link da planilha `Base_FT_Normalizada - Amostra (1 por Categoria)` "
            "na barra lateral ou configure `SHEET_ID` nos Secrets do Streamlit.",
        )

    try:
        df_prod = _limpar_colunas_texto(pd.read_csv(montar_url_csv(sheet_id, ABA_PRODUTOS)))
        df_gar = _limpar_colunas_texto(pd.read_csv(montar_url_csv(sheet_id, ABA_GARANTIAS)))

        faltantes_prod = [c for c in ["id_produto", "categoria", "produto"] if c not in df_prod.columns]
        faltantes_gar = [
            c
            for c in ["id_produto", "ativo_padronizado", "valor_numerico", "unidade"]
            if c not in df_gar.columns
        ]

        if faltantes_prod:
            return (
                pd.DataFrame(),
                pd.DataFrame(),
                horario_sync,
                f"Aba '{ABA_PRODUTOS}' sem colunas obrigatórias: {', '.join(faltantes_prod)}. "
                "Confirme se a planilha está compartilhada como 'Qualquer pessoa com o link (Leitor)'.",
            )
        if faltantes_gar:
            return (
                pd.DataFrame(),
                pd.DataFrame(),
                horario_sync,
                f"Aba '{ABA_GARANTIAS}' sem colunas obrigatórias: {', '.join(faltantes_gar)}.",
            )

        df_prod = df_prod[df_prod["id_produto"] != ""].copy()
        df_gar = df_gar[df_gar["id_produto"] != ""].copy()

        df_gar["valor_numerico"] = pd.to_numeric(
            df_gar["valor_numerico"].astype(str).str.replace(",", ".", regex=False),
            errors="coerce",
        )

        for col in COLUNAS_PRODUTOS:
            if col not in df_prod.columns:
                df_prod[col] = ""
        for col in COLUNAS_GARANTIAS:
            if col not in df_gar.columns:
                df_gar[col] = ""

        resumo_garantias = (
            df_gar.groupby("id_produto")
            .apply(formatar_resumo_garantias_df)
            .reset_index(name="garantias_resumo")
        )
        df_prod = df_prod.merge(resumo_garantias, on="id_produto", how="left")
        df_prod["garantias_resumo"] = df_prod["garantias_resumo"].fillna("Sem garantia declarada")

        df_prod = ordenar_portfolio(df_prod)
        return df_prod, df_gar, horario_sync, None

    except Exception as exc:
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            horario_sync,
            f"Falha ao conectar com a planilha base: {exc}. "
            "Verifique se o compartilhamento está ativo para leitura pública com o link.",
        )


# =============================================================================
# CAMADA DE DOMÍNIO (REGRAS DE NEGÓCIO E CÁLCULOS)
# =============================================================================
def formatar_valor_garantia(valor: float, unidade: str) -> str:
    if pd.isna(valor):
        return "-"
    if unidade.upper() == "UFC/G":
        return f"{valor:.1e} {unidade}"
    if unidade.lower() == "mg/kg":
        return f"{valor:,.0f} {unidade}"
    return f"{valor:.2f}%".replace(".00%", "%").replace(".", ",")


def formatar_resumo_garantias_df(grupo: pd.DataFrame) -> str:
    partes: List[str] = []
    for _, row in grupo.iterrows():
        ativo = str(row.get("ativo_padronizado", "")).strip()
        operador = str(row.get("operador", "")).strip()
        val = row.get("valor_numerico")
        unidade = str(row.get("unidade", "")).strip()
        if not ativo:
            continue
        val_fmt = formatar_valor_garantia(val, unidade)
        prefixo = f"{operador} " if operador else ""
        partes.append(f"{ativo}: {prefixo}{val_fmt}")
    return " | ".join(partes)


def ordenar_portfolio(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena o portfólio priorizando AnOx/Xtendra, Novamold, Salplus, Dresbond e Outros."""

    def peso_ordem(row: pd.Series) -> int:
        texto = f"{row.get('linha', '')} {row.get('categoria', '')} {row.get('produto', '')}".lower()
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
    df_copia = df_copia.sort_values(by=["_ordem", "produto"]).drop(columns=["_ordem"])
    return df_copia.reset_index(drop=True)


def calcular_entrega_ativos(
    id_produto: str,
    dosagem_g_ton: float,
    df_garantias: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Calcula a entrega por molécula a partir da aba Garantias_Ativos.
    - '%'     -> ppm (mg/kg) = dosagem_g_ton * (valor_numerico / 100)
    - 'mg/kg' -> ppm (mg/kg) = dosagem_g_ton * (valor_numerico / 1_000_000)
    - 'UFC/g' -> UFC/g de substrato = (dosagem_g_ton * valor_numerico) / 1_000_000
    """
    gar_prod = df_garantias[df_garantias["id_produto"] == id_produto]
    if gar_prod.empty or dosagem_g_ton <= 0:
        return {
            "detalhe_texto": "Sem garantia numérica aplicável" if gar_prod.empty else "Dosagem 0 g/ton",
            "ppm_primarios": 0.0,
            "ppm_sinergistas": 0.0,
            "tem_ppm": False,
            "observacao_dupla": "",
        }

    ativos_presentes = set(gar_prod["ativo_padronizado"].dropna().tolist())
    ativos_excluidos_soma = set()
    notas_dupla: List[str] = []

    for excluido, mantido in PARES_DUPLA_DECLARACAO:
        if excluido in ativos_presentes and mantido in ativos_presentes:
            ativos_excluidos_soma.add(excluido)
            notas_dupla.append(f"{excluido} não somado por equivalência a {mantido}")

    detalhes: List[str] = []
    ppm_primarios = 0.0
    ppm_sinergistas = 0.0
    tem_ppm = False

    for _, row in gar_prod.iterrows():
        ativo = str(row["ativo_padronizado"]).strip()
        val = row["valor_numerico"]
        unidade = str(row["unidade"]).strip()
        if pd.isna(val):
            continue

        if unidade == "%":
            ppm_mol = dosagem_g_ton * (float(val) / 100.0)
            tem_ppm = True
            detalhes.append(f"{ativo}: {ppm_mol:,.1f} ppm")
            if ativo not in ativos_excluidos_soma:
                if ativo in SINERGISTAS:
                    ppm_sinergistas += ppm_mol
                else:
                    ppm_primarios += ppm_mol
        elif unidade.lower() == "mg/kg":
            ppm_mol = dosagem_g_ton * (float(val) / 1_000_000.0)
            tem_ppm = True
            detalhes.append(f"{ativo}: {ppm_mol:,.3f} ppm")
            if ativo not in ativos_excluidos_soma:
                ppm_primarios += ppm_mol
        elif unidade.upper() == "UFC/G":
            ufc_g_substrato = (dosagem_g_ton * float(val)) / 1_000_000.0
            detalhes.append(f"{ativo}: {ufc_g_substrato:.2e} UFC/g")
        else:
            detalhes.append(f"{ativo}: {val} {unidade}")

    # Quando um acidificante/sinergista é o único ativo garantido (ex.: SALPLUS BALANCE)
    if ppm_primarios == 0.0 and ppm_sinergistas > 0.0:
        ppm_primarios = ppm_sinergistas
        ppm_sinergistas = 0.0

    return {
        "detalhe_texto": " | ".join(detalhes) if detalhes else "Não aplicável (%)",
        "ppm_primarios": ppm_primarios,
        "ppm_sinergistas": ppm_sinergistas,
        "tem_ppm": tem_ppm,
        "observacao_dupla": "; ".join(notas_dupla),
    }


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
) -> Tuple[float, Dict[str, float]]:
    """Calcula volumes industriais mensais (ton/mês) com proteção contra divisão por zero."""
    if tipo_gatilho == "Aves Abatidas":
        aves_mes = max(aves_dia, 0.0) * max(dias_mes, 0)
        racao_calc = (aves_mes * consumo_ave) / 1000.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    elif tipo_gatilho == "Produção de Ração":
        racao_calc = max(racao_input, 0.0)
        aves_mes = (racao_calc * 1000.0) / consumo_ave if consumo_ave > 0 else 0.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    else:
        mp_calc = max(mp_input, 0.0)
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


def gerar_texto_proposta(
    cliente_nome: str,
    cliente_cnpj: str,
    cliente_contato: str,
    linhas_financeiro: List[Dict[str, Any]],
    vol_faturado_total: float,
    fat_mensal_total: float,
    fat_anual_total: float,
) -> str:
    linhas = [
        "# PROPOSTA COMERCIAL - SOLUÇÕES EM NUTRIÇÃO ANIMAL",
        "---",
        f"**Cliente:** {cliente_nome or 'Não especificado'}",
        f"**CNPJ:** {cliente_cnpj or 'N/A'}",
        f"**Contato Responsável:** {cliente_contato or 'N/A'}",
        f"**Data de Emissão:** {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "",
        "## Resumo da Cesta de Tratamento e Investimento (US$)",
    ]
    for lf in linhas_financeiro:
        linhas.append(
            f"- **Produto:** {lf['Produto']} ({lf['Matriz']}) | "
            f"**Dosagem:** {lf['Dosagem (g/ton)']} g/ton | "
            f"**Entrega:** {lf['Entrega por Molécula']} | "
            f"**Obs:** {lf['Observação'] or 'N/A'} | "
            f"**Preço:** US$ {lf['Preço Unitário (US$/kg)']:,.2f}/kg | "
            f"**Custo/ton:** US$ {lf['Custo Tratamento (US$/ton)']:,.2f} | "
            f"**Faturamento Mensal:** US$ {lf['Faturamento Mensal (US$)']:,.2f}"
        )
    linhas.extend(
        [
            "",
            "---",
            f"- **Volume Mensal Estimado (com Share):** {vol_faturado_total:,.1f} kg/mês",
            f"- **Faturamento Mensal Total Estimado:** US$ {fat_mensal_total:,.2f}",
            f"- **Potencial Anualizado:** US$ {fat_anual_total:,.2f}",
        ]
    )
    return "\n".join(linhas)


# =============================================================================
# GESTÃO DE ESTADO (SESSION STATE)
# =============================================================================
def inicializar_sessao(lista_produtos: List[str]) -> None:
    defaults: Dict[str, Any] = {
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


def atualizar_balanco_na_sessao() -> None:
    aves_mes, volumes = calcular_balanco_massa(
        tipo_gatilho=st.session_state.tipo_gatilho,
        aves_dia=float(st.session_state.aves_dia),
        dias_mes=int(st.session_state.dias_mes),
        racao_input=float(st.session_state.racao_input),
        mp_input=float(st.session_state.mp_input),
        consumo_ave=float(st.session_state.consumo_ave),
        peso_ave=float(st.session_state.peso_ave),
        rend_mp_pv=float(st.session_state.rend_mp_pv),
        rend_fvo=float(st.session_state.rend_fvo),
        rend_fps=float(st.session_state.rend_fps),
        rend_oleo=float(st.session_state.rend_oleo),
    )
    st.session_state.aves_mes_calc = aves_mes
    st.session_state.volumes_producao = volumes


# =============================================================================
# CAMADA DE APRESENTAÇÃO (INTERFACE STREAMLIT)
# =============================================================================
def autenticar_usuario() -> bool:
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if st.session_state.autenticado:
        return True

    st.title("🔒 Autenticação Restrita")
    st.markdown("Insira a senha de acesso para utilizar o Ecossistema Comercial.")
    senha_digitada = st.text_input("Senha de Acesso:", type="password")
    if st.button("Entrar", type="primary"):
        if hmac.compare_digest(senha_digitada, obter_senha_app()):
            st.session_state.autenticado = True
            st.rerun()
        else:
            st.error("Senha incorreta. Verifique e tente novamente.")
    return False


def main() -> None:
    if not autenticar_usuario():
        return

    st.title("🐔 Ecossistema Comercial - Nutrição Avícola & Graxaria (US$)")
    st.markdown(
        "Suporte técnico-comercial conectado à base normalizada em 2 abas "
        "(`Produtos` + `Garantias_Ativos`, somente leitura)."
    )

    sheet_id_configurado = obter_sheet_id_secrets()

    with st.sidebar:
        st.header("🔗 Conexão da Base")
        if not sheet_id_configurado:
            url_manual = st.text_input(
                "Link da Planilha Base (2 abas):",
                value=st.session_state.get("sheet_url_manual", ""),
                placeholder="Cole o link da Base_FT_Normalizada - Amostra",
            )
            st.session_state["sheet_url_manual"] = url_manual
            sheet_id = extrair_sheet_id(url_manual)
        else:
            sheet_id = sheet_id_configurado

        df_produtos, df_garantias, horario_sync, erro_carga = carregar_base_normalizada(sheet_id)

        if erro_carga:
            st.error("Base desconectada")
        else:
            st.success(f"Base conectada: {len(df_produtos)} produtos | {len(df_garantias)} garantias")
            st.caption(f"Última sincronização: {horario_sync}")

        if st.button("🔄 Atualizar Base", use_container_width=True):
            carregar_base_normalizada.clear()
            st.rerun()

        st.markdown("---")
        st.header("🧭 Navegação")
        modulo = st.radio(
            "Selecione a Etapa:",
            [
                "0. Cadastro do Cliente & CRM",
                "1. Balanço de Massa & Produção",
                "2. Consulta de FT & Cesta de Tratamento",
                "3. Simulação de Faturamento & Relatório Executivo (US$)",
            ],
        )

    if erro_carga or df_produtos.empty:
        st.error(erro_carga or "A base de dados retornou vazia.")
        st.info(
            "Verifique se a planilha `Base_FT_Normalizada - Amostra (1 por Categoria)` está "
            "compartilhada como **Qualquer pessoa com o link (Leitor)** e cole o link na barra "
            "lateral ou em `SHEET_ID` nos Secrets do Streamlit."
        )
        return

    lista_produtos = df_produtos["produto"].tolist()
    mapa_produtos = df_produtos.set_index("produto").to_dict(orient="index")

    inicializar_sessao(lista_produtos)
    atualizar_balanco_na_sessao()

    # -------------------------------------------------------------------------
    # MÓDULO 0: CADASTRO DO CLIENTE & CRM
    # -------------------------------------------------------------------------
    if modulo == "0. Cadastro do Cliente & CRM":
        st.header("Etapa 0: Identificação e Histórico do Cliente (Base CRM)")
        st.markdown("Cadastre os dados da integração/fábrica para associar às simulações.")

        c_col1, c_col2 = st.columns(2)
        with c_col1:
            st.session_state.cliente_nome = st.text_input(
                "Nome da Empresa / Cliente:",
                value=st.session_state.cliente_nome,
                placeholder="Ex.: Integradora AgroAvícola Ltda",
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
                placeholder="Nome e cargo do nutricionista ou comprador",
            )

        st.markdown("---")
        st.subheader("🗂️ Histórico de Simulações Salvas na Sessão")
        if st.button("💾 Salvar Simulação Atual no CRM", type="primary"):
            if not st.session_state.cliente_nome.strip():
                st.warning("Preencha o Nome da Empresa antes de salvar.")
            else:
                st.session_state.crm_historico.append(
                    {
                        "Data/Hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
                        "Cliente": st.session_state.cliente_nome.strip(),
                        "CNPJ": st.session_state.cliente_cnpj.strip(),
                        "Contato": st.session_state.cliente_contato.strip(),
                        "Ração (ton/mês)": round(st.session_state.volumes_producao["Fábrica de Ração"], 1),
                        "MP FFO (ton/mês)": round(st.session_state.volumes_producao["Matéria-Prima Bruta FFO"], 1),
                        "Itens na Cesta": len(st.session_state.cesta_aplicacao),
                    }
                )
                st.success(f"Simulação para '{st.session_state.cliente_nome}' salva no histórico.")

        if st.session_state.crm_historico:
            df_crm = pd.DataFrame(st.session_state.crm_historico)
            st.dataframe(df_crm, use_container_width=True, hide_index=True)
            st.download_button(
                label="⬇️ Exportar Histórico CRM (CSV)",
                data=df_crm.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"crm_simulacoes_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
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

        opcoes_gatilho = ["Aves Abatidas", "Produção de Ração", "Matéria-Prima FFO Recebida"]
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
                    value=float(st.session_state.rend_mp_pv),
                    step=0.5,
                )
            with p_c2:
                st.session_state.rend_fvo = st.number_input(
                    "Rendimento FVO s/ MP (%):",
                    min_value=1.0,
                    value=float(st.session_state.rend_fvo),
                    step=0.5,
                )
                st.session_state.rend_fps = st.number_input(
                    "Rendimento FPS s/ MP (%):",
                    min_value=1.0,
                    value=float(st.session_state.rend_fps),
                    step=0.5,
                )
                st.session_state.rend_oleo = st.number_input(
                    "Rendimento Óleo s/ MP (%):",
                    min_value=1.0,
                    value=float(st.session_state.rend_oleo),
                    step=0.1,
                )

        atualizar_balanco_na_sessao()
        vols = st.session_state.volumes_producao

        st.markdown("---")
        st.success(
            f"📊 **Painel de Volumes Estimados "
            f"(Equivalente a {st.session_state.aves_mes_calc:,.0f} aves/mês):**"
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

        with st.expander("🔍 Consultar Catálogo e Filtrar por Princípio Ativo (Match Direto)", expanded=True):
            cat_disp = sorted(df_produtos["categoria"].dropna().unique().tolist())
            est_disp = sorted(df_produtos["estado_fisico"].dropna().unique().tolist())
            ativos_disp = sorted(df_garantias["ativo_padronizado"].dropna().unique().tolist())

            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                f_cat = st.multiselect("Categoria:", options=cat_disp, default=cat_disp)
            with col_f2:
                f_est = st.multiselect("Estado Físico:", options=est_disp, default=est_disp)
            with col_f3:
                f_ativos = st.multiselect("Conter Princípio(s) Ativo(s) (Match Exato):", options=ativos_disp)

            df_ft_view = df_produtos.copy()
            if f_cat:
                df_ft_view = df_ft_view[df_ft_view["categoria"].isin(f_cat)]
            if f_est:
                df_ft_view = df_ft_view[df_ft_view["estado_fisico"].isin(f_est)]

            if f_ativos:
                ids_validos = set(df_ft_view["id_produto"].tolist())
                for atv in f_ativos:
                    ids_com_ativo = set(
                        df_garantias.loc[
                            df_garantias["ativo_padronizado"] == atv, "id_produto"
                        ].tolist()
                    )
                    ids_validos &= ids_com_ativo
                df_ft_view = df_ft_view[df_ft_view["id_produto"].isin(ids_validos)]

            colunas_exibicao = [
                "categoria",
                "produto",
                "estado_fisico",
                "garantias_resumo",
                "limite_regulatorio",
                "composicao",
                "ft_revisao",
                "ft_data",
            ]
            if df_ft_view.empty:
                st.warning("Nenhum produto encontrado com a combinação de filtros selecionada.")
            else:
                st.dataframe(
                    df_ft_view[colunas_exibicao].rename(
                        columns={
                            "categoria": "Categoria",
                            "produto": "Produto",
                            "estado_fisico": "Estado Físico",
                            "garantias_resumo": "Garantias Declaradas",
                            "limite_regulatorio": "Limite Regulatório",
                            "composicao": "Composição (Referência)",
                            "ft_revisao": "Revisão FT",
                            "ft_data": "Data FT",
                        }
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

        st.markdown("---")
        st.subheader("🛒 Cesta de Tratamento (Múltiplos Pontos de Aplicação)")
        st.markdown(
            "Adicione ou duplique linhas para dosar múltiplos produtos. "
            "A dosagem é sempre em **g/ton** e a entrega de **ppm** é detalhada por molécula."
        )

        matrizes_opcoes = st.session_state.volumes_producao
        itens_para_remover: List[int] = []
        itens_para_duplicar: List[Dict[str, Any]] = []
        resumo_cesta: List[Dict[str, Any]] = []

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            c1, c2, c3, c4, c5, c6 = st.columns([2.2, 2.8, 1.5, 2.5, 1.0, 0.6])

            with c1:
                lista_mat = list(matrizes_opcoes.keys())
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

            vol_base = float(matrizes_opcoes.get(item["matriz"], 0.0))
            consumo_linha_kg = (vol_base * float(item["dosagem"])) / 1000.0

            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            est_fisico = str(info_p.get("estado_fisico", ""))
            comp_str = str(info_p.get("composicao", ""))
            limite_reg = str(info_p.get("limite_regulatorio", ""))
            rev_ft = str(info_p.get("ft_revisao", ""))

            entrega = calcular_entrega_ativos(id_prod, float(item["dosagem"]), df_garantias)

            nota_dupla = f" *(Nota: {entrega['observacao_dupla']})*" if entrega["observacao_dupla"] else ""
            st.caption(
                f"📌 **{item['produto']} ({est_fisico} | {rev_ft})** | "
                f"**Entrega por Molécula:** {entrega['detalhe_texto']}{nota_dupla} | "
                f"**Limite Reg.:** {limite_reg} | **Composição:** {comp_str}"
            )
            st.markdown("---")

            resumo_cesta.append(
                {
                    "Ponto": idx + 1,
                    "Matriz Aplicada": item["matriz"],
                    "Volume Matriz (ton/mês)": round(vol_base, 1),
                    "Produto Comercial": item["produto"],
                    "Estado Físico": est_fisico,
                    "Dosagem (g/ton)": round(float(item["dosagem"]), 1),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Ativos Primários (ppm)": (
                        round(entrega["ppm_primarios"], 2) if entrega["tem_ppm"] else "N/A"
                    ),
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
        st.subheader("📋 Quadro Consolidado de Consumo e Entrega em ppm")
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
        linhas_financeiro: List[Dict[str, Any]] = []

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            vol_base = float(matrizes_opcoes.get(item["matriz"], 0.0))
            dosagem = float(item["dosagem"])
            consumo_kg_100 = (vol_base * dosagem) / 1000.0

            info_p = mapa_produtos.get(item["produto"], {})
            entrega = calcular_entrega_ativos(str(info_p.get("id_produto", "")), dosagem, df_garantias)

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(f"**{idx + 1}. {item['produto']}** *(em {item['matriz']})*")
                st.caption(
                    f"Dosagem: {dosagem:,.0f} g/ton | {entrega['detalhe_texto']} | "
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

            preco_kg = float(item["preco_kg"])
            share = int(item["share"])
            consumo_real_kg = consumo_kg_100 * (share / 100.0)
            faturamento_item = consumo_real_kg * preco_kg
            custo_ton_tratada = (dosagem / 1000.0) * preco_kg

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
                    "Dosagem (g/ton)": round(dosagem, 1),
                    "Entrega por Molécula": entrega["detalhe_texto"],
                    "Observação": item.get("observacao", ""),
                    "Custo Tratamento (US$/ton)": round(custo_ton_tratada, 2),
                    "Share (%)": share,
                    "Volume Faturado (kg/mês)": round(consumo_real_kg, 2),
                    "Preço Unitário (US$/kg)": round(preco_kg, 2),
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
        texto_proposta = gerar_texto_proposta(
            cliente_nome=st.session_state.cliente_nome,
            cliente_cnpj=st.session_state.cliente_cnpj,
            cliente_contato=st.session_state.cliente_contato,
            linhas_financeiro=linhas_financeiro,
            vol_faturado_total=vol_faturado_total,
            fat_mensal_total=fat_mensal_total,
            fat_anual_total=fat_anual_total,
        )

        col_p1, col_p2 = st.columns([1, 1])
        with col_p1:
            mostrar_proposta = st.button("Gerar Proposta Comercial na Tela", type="primary")
        with col_p2:
            st.download_button(
                label="⬇️ Baixar Proposta (.md)",
                data=texto_proposta.encode("utf-8"),
                file_name=f"proposta_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
            )

        if mostrar_proposta:
            st.markdown(texto_proposta)


if __name__ == "__main__":
    main()
