import hmac
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import streamlit as st
from fpdf import FPDF

# =============================================================================
# CONFIGURAÇÃO DA PÁGINA E CONSTANTES
# =============================================================================
st.set_page_config(
    page_title="Ecossistema Comercial - Nutrição Avícola & Graxaria",
    page_icon="📊",
    layout="wide",
)

SHEET_ID = "1zTclMBgggOlYfrwRQRIRvSVAVOHUdOVPA4EB1VopcHI"
ABA_PRODUTOS = "Produtos"
ABA_GARANTIAS = "Garantias_Ativos"
LOGO_PATH = "logo_cfs.png"

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
def obter_senha_app() -> str:
    try:
        return str(st.secrets.get("APP_PASSWORD", "cfs2026"))
    except Exception:
        return "cfs2026"


def montar_url_csv(nome_aba: str) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
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


@st.cache_data(ttl=300, show_spinner="Sincronizando base de produtos e garantias...")
def carregar_base_normalizada() -> Tuple[pd.DataFrame, pd.DataFrame, str, Optional[str]]:
    horario_sync = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    try:
        df_prod = _limpar_colunas_texto(pd.read_csv(montar_url_csv(ABA_PRODUTOS)))
        df_gar = _limpar_colunas_texto(pd.read_csv(montar_url_csv(ABA_GARANTIAS)))

        faltantes_prod = [c for c in ["id_produto", "categoria", "produto"] if c not in df_prod.columns]
        faltantes_gar = [
            c for c in ["id_produto", "ativo_padronizado", "valor_numerico", "unidade"]
            if c not in df_gar.columns
        ]
        if faltantes_prod:
            return pd.DataFrame(), pd.DataFrame(), horario_sync, f"Aba '{ABA_PRODUTOS}' sem colunas: {', '.join(faltantes_prod)}."
        if faltantes_gar:
            return pd.DataFrame(), pd.DataFrame(), horario_sync, f"Aba '{ABA_GARANTIAS}' sem colunas: {', '.join(faltantes_gar)}."

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
        return pd.DataFrame(), pd.DataFrame(), horario_sync, f"Falha ao conectar com a planilha base: {exc}."


# =============================================================================
# CAMADA DE DOMÍNIO (FORMATAÇÃO BR, ENTRADA NUMÉRICA, CÁLCULOS E PDF)
# =============================================================================
def fmt_br(valor: float, casas: int = 2) -> str:
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def parse_numero_br(texto: str, fallback: float) -> Tuple[float, bool]:
    limpo = str(texto or "").strip().replace(" ", "")
    if not limpo:
        return fallback, False
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif re.match(r"^\d{1,3}(\.\d{3})+$", limpo):
        limpo = limpo.replace(".", "")
    try:
        return float(limpo), True
    except ValueError:
        return fallback, False


def input_numero_br(
    label: str,
    value: float,
    key: str,
    casas: int = 2,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    obs: str = "",
) -> float:
    raw = st.text_input(label, value=fmt_br(float(value), casas), key=key)
    if obs:
        st.markdown(
            f"<div style='color:#6c757d; font-style:italic; font-size:0.82rem; "
            f"margin-top:-12px; margin-bottom:10px;'>{obs}</div>",
            unsafe_allow_html=True,
        )
    num, ok = parse_numero_br(raw, float(value))
    if not ok:
        st.warning(f"Valor inválido em '{label}'. Use números (ex.: 1.250,50).")
        return float(value)
    if min_value is not None and num < min_value:
        num = min_value
    if max_value is not None and num > max_value:
        num = max_value
    return num


def input_inteiro_br(
    label: str,
    value: int,
    key: str,
    min_value: Optional[int] = None,
    max_value: Optional[int] = None,
    obs: str = "",
) -> int:
    num = input_numero_br(
        label=label,
        value=float(value),
        key=key,
        casas=0,
        min_value=float(min_value) if min_value is not None else None,
        max_value=float(max_value) if max_value is not None else None,
        obs=obs,
    )
    return int(round(num))


def pdf_safe(texto: Any) -> str:
    s = str(texto or "").replace("—", "-").replace("–", "-").replace("•", "-")
    return s.encode("latin-1", "replace").decode("latin-1")


def formatar_valor_garantia(valor: float, unidade: str) -> str:
    if pd.isna(valor):
        return "-"
    if unidade.upper() == "UFC/G":
        return f"{valor:.1e} {unidade}".replace(".", ",")
    if unidade.lower() == "mg/kg":
        return f"{fmt_br(float(valor), 0)} {unidade}"
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


def resumo_curto_ativo_pdf(id_produto: str, df_garantias: pd.DataFrame) -> str:
    gar = df_garantias[df_garantias["id_produto"] == id_produto]
    if gar.empty:
        return ""
    partes: List[str] = []
    for _, row in gar.iterrows():
        ativo = str(row.get("ativo_padronizado", "")).strip()
        val = row.get("valor_numerico")
        unidade = str(row.get("unidade", "")).strip()
        if not ativo or pd.isna(val):
            continue
        partes.append(f"{ativo} {formatar_valor_garantia(float(val), unidade)}")
    return ", ".join(partes[:3])


def ordenar_portfolio(df: pd.DataFrame) -> pd.DataFrame:
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
            detalhes.append(f"{ativo}: {fmt_br(ppm_mol, 1)} ppm")
            if ativo not in ativos_excluidos_soma:
                if ativo in SINERGISTAS:
                    ppm_sinergistas += ppm_mol
                else:
                    ppm_primarios += ppm_mol
        elif unidade.lower() == "mg/kg":
            ppm_mol = dosagem_g_ton * (float(val) / 1_000_000.0)
            tem_ppm = True
            detalhes.append(f"{ativo}: {fmt_br(ppm_mol, 3)} ppm")
            if ativo not in ativos_excluidos_soma:
                ppm_primarios += ppm_mol
        elif unidade.upper() == "UFC/G":
            ufc_g_substrato = (dosagem_g_ton * float(val)) / 1_000_000.0
            detalhes.append(f"{ativo}: {ufc_g_substrato:.2e} UFC/g".replace(".", ","))
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
    rend_fv: float,
    rend_fps: float,
    rend_oleo: float,
) -> Tuple[float, Dict[str, float]]:
    if tipo_gatilho == "Aves Abatidas":
        aves_mes = max(aves_dia, 0.0) * max(dias_mes, 0)
        racao_calc = (aves_mes * consumo_ave) / 1000.0
        mp_calc = ((aves_mes * peso_ave) * (rend_mp_pv / 100.0)) / 1000.0
    elif tipo_gatilho == "Produção de Ração":
        racao_calc = max(racao_input, 0.0)
        aves_mes = (racao_calc * 1000.0) / consumo
   if __name__ == "__main__":
        main()
