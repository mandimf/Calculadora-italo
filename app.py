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
    """Aceita URL do Google Sheets, URL do Google Drive (?id= ou /file/d/) ou ID puro."""
    texto = valor.strip().strip('"').strip("'")
    if not texto or "COLE_AQUI" in texto.upper():
        return ""
    for padrao in (
        r"/spreadsheets/d/([a-zA-Z0-9-_]+)",
        r"/file/d/([a-zA-Z0-9-_]+)",
        r"[?&]id=([a-zA-Z0-9-_]+)",
    ):
        match = re.search(padrao, texto)
        if match:
            return match.group(1)
    if "/" in texto or " " in texto:
        return ""
    return texto


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
            f"- **Produto:** {lf.get('Produto', '-')} ({lf.get('Matriz', '-')}) | "
            f"**Dosagem:** {lf.get('Dosagem (g/ton)', 0.0)} g/ton | "
            f"**Entrega:** {lf.get('Entrega por Molécula', '-')} | "
            f"**Obs:** {lf.get('Observação') or 'N/A'} | "
            f"**Preço:** US$ {float(lf.get('Preço Unitário (US$/kg)', 0.0)):,.2f}/kg | "
            f"**Custo/ton:** US$ {float(lf.get('Custo Tratamento (US$/ton)', 0.0)):,.2f} | "
            f"**Faturamento Mensal:** US$ {float(lf.get('Faturamento Mensal (US$)', 0.0)):,.2f}"
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
        mp_input=float(st.session
