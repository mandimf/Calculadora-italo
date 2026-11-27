import hmac
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd
import streamlit as st
from fpdf import FPDF

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
        "Farinha de Vísceras (FV)": mp_calc * (rend_fv / 100.0),
        "Farinha de Penas (FPS)": mp_calc * (rend_fps / 100.0),
        "Óleo de Frango": mp_calc * (rend_oleo / 100.0),
    }
    return aves_mes, volumes


class PropostaCFSPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-18)
        self.set_draw_color(210, 215, 220)
        self.line(15, self.get_y(), 195, self.get_y())
        self.ln(3)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(100, 110, 120)
        self.cell(0, 5, "BRINGING SCIENCE TO EVERYDAY LIFE", align="C", ln=0)


def gerar_pdf_proposta(
    consultor_nome: str,
    consultor_email: str,
    consultor_telefone: str,
    cliente_nome: str,
    cliente_cnpj: str,
    cliente_contato: str,
    cliente_email: str,
    incoterm: str,
    destino: str,
    expedicao_dias: int,
    validade_str: str,
    pagamento: str,
    obs_gerais: str,
    modo_tecnico: bool,
    linhas_proposta: List[Dict[str, Any]],
) -> bytes:
    pdf = PropostaCFSPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=24)
    pdf.set_margins(15, 14, 15)
    pdf.add_page()

    pdf.set_xy(15, 14)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(15, 35, 65)
    pdf.cell(115, 8, pdf_safe("Proposta Comercial"), ln=1)

    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(90, 95, 105)
    pdf.cell(115, 5, pdf_safe(f"Emissão: {datetime.now().strftime('%d/%m/%Y')}"), ln=0)

    logo_inserido = False
    if os.path.exists(LOGO_PATH):
        try:
            pdf.image(LOGO_PATH, x=155, y=12, w=40)
            logo_inserido = True
        except Exception:
            logo_inserido = False

    if not logo_inserido:
        pdf.set_xy(125, 15)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(0, 74, 153)
        pdf.cell(70, 6, "CFS  Camlin Fine Sciences", align="R", ln=0)

    pdf.set_draw_color(0, 74, 153)
    pdf.set_line_width(0.6)
    pdf.line(15, 31, 195, 31)
    pdf.set_y(36)

    y_info = pdf.get_y()

    pdf.set_xy(15, y_info)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(0, 74, 153)
    pdf.cell(85, 5, "FORNECEDOR", ln=1)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(85, 5, pdf_safe(consultor_nome or "Consultor CFS"), ln=1)
    pdf.set_x(15)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    contato_forn = " | ".join([x for x in [consultor_email, consultor_telefone] if x.strip()])
    pdf.multi_cell(85, 4.5, pdf_safe(contato_forn or "Camlin Fine Sciences"))
    y_fim_forn = pdf.get_y()

    pdf.set_xy(105, y_info)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(0, 74, 153)
    pdf.cell(90, 5, "CLIENTE", ln=1)
    pdf.set_x(105)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(90, 5, pdf_safe(cliente_nome or "Não especificado"), ln=1)
    pdf.set_x(105)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(80, 80, 80)
    linha_ac_partes: List[str] = []
    if cliente_contato.strip():
        linha_ac_partes.append(f"A/C: {cliente_contato.strip()}")
    if cliente_email.strip():
        linha_ac_partes.append(cliente_email.strip())
    if cliente_cnpj.strip():
        linha_ac_partes.append(f"CNPJ: {cliente_cnpj.strip()}")
    texto_ac = " | ".join(linha_ac_partes) if linha_ac_partes else "-"
    pdf.multi_cell(90, 4.5, pdf_safe(texto_ac))
    y_fim_cli = pdf.get_y()

    pdf.set_y(max(y_fim_forn, y_fim_cli) + 8)

    col_preco = f"Preço {incoterm}"
    if modo_tecnico:
        headers = ["Produto / Descrição", "Dosagem", "Qtd. mensal", col_preco, "Custo/ton", "Observação / Aplicação"]
        widths = [50, 20, 24, 24, 22, 40]
        aligns = ["L", "C", "R", "R", "R", "L"]
    else:
        headers = ["Produto / Descrição", "Quantidade mensal", col_preco, "Observação / Aplicação"]
        widths = [64, 32, 32, 52]
        aligns = ["L", "R", "R", "L"]

    pdf.set_fill_color(15, 35, 65)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8.5)
    for h, w, al in zip(headers, widths, aligns):
        pdf.cell(w, 8, pdf_safe(h), border=0, align=al, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(30, 30, 30)
    pdf.set_draw_color(220, 225, 230)
    pdf.set_line_width(0.25)

    for idx_row, lp in enumerate(linhas_proposta):
        desc_prod = lp["produto_pdf"]
        qtd_str = f"{fmt_br(lp['qtd_mensal'], 0)} kg"
        preco_str = f"USD {fmt_br(lp['preco_kg'], 2)}/kg"
        obs_str = lp["obs_pdf"] or "-"

        if modo_tecnico:
            valores = [desc_prod, f"{fmt_br(lp['dosagem'], 0)} g/t", qtd_str, preco_str, f"USD {fmt_br(lp['custo_ton'], 2)}", obs_str]
        else:
            valores = [desc_prod, qtd_str, preco_str, obs_str]

        line_h = 5.0
        max_lines = 1
        for val_txt, w in zip(valores, widths):
            linhas_calc = pdf.multi_cell(w - 2, line_h, pdf_safe(val_txt), split_only=True)
            max_lines = max(max_lines, len(linhas_calc))
        row_h = max(8.0, max_lines * line_h + 2.5)

        if pdf.get_y() + row_h > 268:
            pdf.add_page()

        x_start = 15.0
        y_start = pdf.get_y()
        if idx_row % 2 == 1:
            pdf.set_fill_color(246, 248, 251)
            pdf.rect(x_start, y_start, sum(widths), row_h, style="F")

        cur_x = x_start
        for val_txt, w, al in zip(valores, widths, aligns):
            pdf.set_xy(cur_x + 1, y_start + 1.2)
            pdf.multi_cell(w - 2, line_h, pdf_safe(val_txt), border=0, align=al)
            cur_x += w

        pdf.line(x_start, y_start + row_h, x_start + sum(widths), y_start + row_h)
        pdf.set_y(y_start + row_h)

    pdf.ln(8)

    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(15, 35, 65)
    pdf.cell(0, 6, pdf_safe("Condições Comerciais"), ln=1)
    pdf.ln(1)

    incoterm_full = f"{incoterm} - {destino}" if destino.strip() else incoterm
    condicoes = [
        ("Incoterm:", incoterm_full),
        ("Expedição:", f"{expedicao_dias} dias úteis"),
        ("Validade da proposta:", validade_str),
        ("Pagamento:", pagamento),
    ]
    for rotulo, valor in condicoes:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(50, 55, 65)
        pdf.cell(42, 5.5, pdf_safe(rotulo), ln=0)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 5.5, pdf_safe(valor), ln=1)

    if obs_gerais.strip():
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 8.5)
        pdf.set_text_color(70, 75, 85)
        pdf.cell(0, 5, pdf_safe("Observações Gerais:"), ln=1)
        pdf.set_font("Helvetica", "", 8.5)
        pdf.set_text_color(60, 60, 60)
        pdf.multi_cell(0, 4.5, pdf_safe(obs_gerais.strip()))

    saida = pdf.output()
    return bytes(saida) if isinstance(saida, (bytes, bytearray)) else saida.encode("latin-1")


def inicializar_sessao(lista_produtos: List[str]) -> None:
    defaults: Dict[str, Any] = {
        "consultor_nome": "",
        "consultor_email": "",
        "consultor_telefone": "",
        "cliente_nome": "",
        "cliente_cnpj": "",
        "cliente_contato": "",
        "cliente_email": "",
        "tipo_gatilho": "Aves Abatidas",
        "aves_dia": 50000.0,
        "dias_mes": 25,
        "racao_input": 7500.0,
        "mp_input": 3750.0,
        "consumo_ave": 5.0,
        "peso_ave": 3.0,
        "rend_mp_pv": 30.0,
        "rend_fv": 25.0,
        "rend_fps": 10.0,
        "rend_oleo": 12.67,
        "next_id": 3,
        "crm_historico": [],
        "incoterm": "CIF",
        "destino": "",
        "expedicao_dias": 5,
        "validade_proposta": date.today() + timedelta(days=30),
        "pagamento": "30 dias",
        "obs_gerais_pdf": "",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    prod_inicial = lista_produtos[0] if lista_produtos else ""
    if "cesta_aplicacao" not in st.session_state:
        st.session_state.cesta_aplicacao = [
            {
                "id": 1,
                "matriz": "Farinha de Vísceras (FV)",
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
        rend_fv=float(st.session_state.rend_fv),
        rend_fps=float(st.session_state.rend_fps),
        rend_oleo=float(st.session_state.rend_oleo),
    )
    st.session_state.aves_mes_calc = aves_mes
    st.session_state.volumes_producao = volumes


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
    st.markdown("Suporte técnico-comercial conectado diretamente à base oficial (somente leitura).")

    df_produtos, df_garantias, horario_sync, erro_carga = carregar_base_normalizada()

    with st.sidebar:
        if erro_carga:
            st.error("Falha na sincronização")
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
                "0. Cadastro do Cliente & Consultor",
                "1. Balanço de Massa & Produção",
                "2. Consulta de FT & Cesta de Tratamento",
                "3. Simulação de Faturamento & Proposta PDF (US$)",
            ],
        )

    if erro_carga or df_produtos.empty:
        st.error(erro_carga or "A base de dados retornou vazia.")
        return

    lista_produtos = df_produtos["produto"].tolist()
    mapa_produtos = df_produtos.set_index("produto").to_dict(orient="index")

    inicializar_sessao(lista_produtos)
    atualizar_balanco_na_sessao()

    if modulo == "0. Cadastro do Cliente & Consultor":
        st.header("Etapa 0: Identificação do Consultor, Cliente e Histórico (CRM)")
        col_forn, col_cli = st.columns(2)
        with col_forn:
            st.subheader("👔 Dados do Fornecedor (Consultor CFS)")
            st.session_state.consultor_nome = st.text_input("Nome do Consultor:", value=st.session_state.consultor_nome, placeholder="Ex.: Diogo Bracciali")
            st.session_state.consultor_email = st.text_input("E-mail Corporativo:", value=st.session_state.consultor_email, placeholder="nome.sobrenome@camlinfs.com")
            st.session_state.consultor_telefone = st.text_input("Telefone / WhatsApp:", value=st.session_state.consultor_telefone, placeholder="+55 (19) 99999-9999")
        with col_cli:
            st.subheader("🏢 Dados do Cliente")
            st.session_state.cliente_nome = st.text_input("Nome da Empresa / Cliente:", value=st.session_state.cliente_nome, placeholder="Ex.: FVO Brasília")
            st.session_state.cliente_cnpj = st.text_input("CNPJ:", value=st.session_state.cliente_cnpj, placeholder="00.000.000/0001-00")
            st.session_state.cliente_contato = st.text_input("Responsável (A/C):", value=st.session_state.cliente_contato, placeholder="Ex.: Thiago Soares")
            st.session_state.cliente_email = st.text_input("E-mail do Cliente:", value=st.session_state.cliente_email, placeholder="contato@empresa.com.br")

        st.markdown("---")
        st.subheader("🗂️ Histórico de Simulações Salvas na Sessão")
        if st.button("💾 Salvar Simulação Atual no CRM", type="primary"):
            if not st.session_state.cliente_nome.strip():
                st.warning("Preencha o Nome da Empresa antes de salvar.")
            else:
                st.session_state.crm_historico.append({
                    "Data/Hora": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "Consultor": st.session_state.consultor_nome.strip(),
                    "Cliente": st.session_state.cliente_nome.strip(),
                    "CNPJ": st.session_state.cliente_cnpj.strip(),
                    "Contato": st.session_state.cliente_contato.strip(),
                    "E-mail": st.session_state.cliente_email.strip(),
                    "Ração (ton/mês)": fmt_br(st.session_state.volumes_producao["Fábrica de Ração"], 1),
                    "MP FFO (ton/mês)": fmt_br(st.session_state.volumes_producao["Matéria-Prima Bruta FFO"], 1),
                    "Itens na Cesta": len(st.session_state.cesta_aplicacao),
                })
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
                st.session_state.aves_dia = input_numero_br(
                    "Abate Diário (aves/dia):",
                    value=float(st.session_state.aves_dia),
                    key="in_aves_dia",
                    casas=0,
                    min_value=1.0,
                )
                st.session_state.dias_mes = input_inteiro_br(
                    "Dias de Operação / Mês:",
                    value=int(st.session_state.dias_mes),
                    key="in_dias_mes",
                    min_value=1,
                    max_value=31,
                )
            elif st.session_state.tipo_gatilho == "Produção de Ração":
                st.session_state.racao_input = input_numero_br(
                    "Volume de Ração Produzida (ton/mês):",
                    value=float(st.session_state.racao_input),
                    key="in_racao",
                    casas=1,
                    min_value=1.0,
                )
            else:
                st.session_state.mp_input = input_numero_br(
                    "Matéria-Prima Bruta Recebida na FFO (ton/mês):",
                    value=float(st.session_state.mp_input),
                    key="in_mp",
                    casas=1,
                    min_value=1.0,
                )

        with col2:
            st.subheader("⚙️ Índices Zootécnicos e Industriais")
            p_c1, p_c2 = st.columns(2)
            with p_c1:
                st.session_state.consumo_ave = input_numero_br(
                    "Consumo Ração/Ave (kg):",
                    value=float(st.session_state.consumo_ave),
                    key="in_consumo_ave",
                    casas=2,
                    min_value=0.1,
                    obs="Consumo total de ração pela ave até o abate.",
                )
                st.session_state.peso_ave = input_numero_br(
                    "Peso Vivo Médio (kg):",
                    value=float(st.session_state.peso_ave),
                    key="in_peso_ave",
                    casas=2,
                    min_value=0.1,
                    obs="Peso vivo médio da ave no momento do abate.",
                )
                st.session_state.rend_mp_pv = input_numero_br(
                    "Rendimento MP s/ PV (%):",
                    value=float(st.session_state.rend_mp_pv),
                    key="in_rend_mp_pv",
                    casas=2,
                    min_value=1.0,
                    obs="Proporção do PV que é destinado na forma de matéria-prima para FFO.",
                )
            with p_c2:
                st.session_state.rend_fv = input_numero_br(
                    "Rendimento FV s/ MP (%):",
                    value=float(st.session_state.rend_fv),
                    key="in_rend_fv",
                    casas=2,
                    min_value=1.0,
                    obs="Proporção da MP que é convertida em farinha de vísceras.",
                )
                st.session_state.rend_fps = input_numero_br(
                    "Rendimento FPS s/ MP (%):",
                    value=float(st.session_state.rend_fps),
                    key="in_rend_fps",
                    casas=2,
                    min_value=1.0,
                    obs="Proporção da MP que é convertida em farinha de penas e sangue.",
                )
                st.session_state.rend_oleo = input_numero_br(
                    "Rendimento Óleo s/ MP (%):",
                    value=float(st.session_state.rend_oleo),
                    key="in_rend_oleo",
                    casas=2,
                    min_value=1.0,
                    obs="Proporção da MP que é convertida em óleo de aves.",
                )

        atualizar_balanco_na_sessao()
        vols = st.session_state.volumes_producao

        st.markdown("---")
        st.success(f"📊 **Painel de Volumes Estimados (Equivalente a {fmt_br(st.session_state.aves_mes_calc, 0)} aves/mês):**")
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Ração Produzida", f"{fmt_br(vols['Fábrica de Ração'], 1)} ton")
        m2.metric("Matéria-Prima FFO", f"{fmt_br(vols['Matéria-Prima Bruta FFO'], 1)} ton")
        m3.metric("Farinha Vísceras (FV)", f"{fmt_br(vols['Farinha de Vísceras (FV)'], 1)} ton")
        m4.metric("Farinha Penas (FPS)", f"{fmt_br(vols['Farinha de Penas (FPS)'], 1)} ton")
        m5.metric("Óleo de Frango", f"{fmt_br(vols['Óleo de Frango'], 1)} ton")

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
                f_ativos = st.multiselect("Conter Princípio(s) Ativo(s):", options=ativos_disp)

            df_ft_view = df_produtos.copy()
            if f_cat:
                df_ft_view = df_ft_view[df_ft_view["categoria"].isin(f_cat)]
            if f_est:
                df_ft_view = df_ft_view[df_ft_view["estado_fisico"].isin(f_est)]
            if f_ativos:
                ids_validos = set(df_ft_view["id_produto"].tolist())
                for atv in f_ativos:
                    ids_com_ativo = set(df_garantias.loc[df_garantias["ativo_padronizado"] == atv, "id_produto"].tolist())
                    ids_validos &= ids_com_ativo
                df_ft_view = df_ft_view[df_ft_view["id_produto"].isin(ids_validos)]

            colunas_exibicao = ["categoria", "produto", "estado_fisico", "garantias_resumo", "limite_regulatorio", "composicao", "ft_revisao", "ft_data"]
            if df_ft_view.empty:
                st.warning("Nenhum produto encontrado com a combinação de filtros selecionada.")
            else:
                st.dataframe(
                    df_ft_view[colunas_exibicao].rename(columns={
                        "categoria": "Categoria",
                        "produto": "Produto",
                        "estado_fisico": "Estado Físico",
                        "garantias_resumo": "Garantias Declaradas",
                        "limite_regulatorio": "Limite Regulatório",
                        "composicao": "Composição (Referência)",
                        "ft_revisao": "Revisão FT",
                        "ft_data": "Data FT",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )

        st.markdown("---")
        st.subheader("🛒 Cesta de Tratamento (Múltiplos Pontos de Aplicação)")
        matrizes_opcoes = st.session_state.volumes_producao
        itens_para_remover: List[int] = []
        itens_para_duplicar: List[Dict[str, Any]] = []
        resumo_cesta: List[Dict[str, Any]] = []
        total_kg_geral = 0.0

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            c1, c2, c3, c4, c5, c6 = st.columns([2.2, 2.8, 1.5, 2.5, 1.0, 0.6])
            with c1:
                lista_mat = list(matrizes_opcoes.keys())
                mat_idx = lista_mat.index(item["matriz"]) if item["matriz"] in lista_mat else 0
                item["matriz"] = st.selectbox(f"Matriz #{idx + 1}:", options=lista_mat, index=mat_idx, key=f"matriz_{item['id']}")
            with c2:
                prod_idx = lista_produtos.index(item["produto"]) if item["produto"] in lista_produtos else 0
                item["produto"] = st.selectbox(f"Produto #{idx + 1}:", options=lista_produtos, index=prod_idx, key=f"prod_{item['id']}")
            with c3:
                item["dosagem"] = input_numero_br(
                    f"g/ton #{idx + 1}:",
                    value=float(item["dosagem"]),
                    key=f"dose_{item['id']}",
                    casas=1,
                    min_value=0.0,
                )
            with c4:
                item["observacao"] = st.text_input(f"Observação #{idx + 1}:", value=str(item.get("observacao", "")), key=f"obs_{item['id']}")
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
            total_kg_geral += consumo_linha_kg
            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            est_fisico = str(info_p.get("estado_fisico", ""))
            comp_str = str(info_p.get("composicao", ""))
            limite_reg = str(info_p.get("limite_regulatorio", ""))
            rev_ft = str(info_p.get("ft_revisao", ""))
            entrega = calcular_entrega_ativos(id_prod, float(item["dosagem"]), df_garantias)

            nota_dupla = f" *(Nota: {entrega['observacao_dupla']})*" if entrega["observacao_dupla"] else ""
            st.caption(f"📌 **{item['produto']} ({est_fisico} | {rev_ft})** | **Entrega:** {entrega['detalhe_texto']}{nota_dupla} | **Limite Reg.:** {limite_reg} | **Composição:** {comp_str}")
            st.markdown("---")

            resumo_cesta.append({
                "Ponto": idx + 1,
                "Matriz Aplicada": item["matriz"],
                "Volume Matriz (ton/mês)": fmt_br(vol_base, 1),
                "Produto Comercial": item["produto"],
                "Estado Físico": est_fisico,
                "Dosagem (g/ton)": fmt_br(float(item["dosagem"]), 1),
                "Entrega por Molécula": entrega["detalhe_texto"],
                "Ativos Primários (ppm)": fmt_br(entrega["ppm_primarios"], 2) if entrega["tem_ppm"] else "N/A",
                "Observação": item["observacao"],
                "Consumo Mensal (kg)": fmt_br(consumo_linha_kg, 2),
            })

        if itens_para_duplicar:
            for it in itens_para_duplicar:
                novo_item = it.copy()
                novo_item["id"] = st.session_state.next_id
                st.session_state.cesta_aplicacao.append(novo_item)
                st.session_state.next_id += 1
            st.rerun()

        if itens_para_remover:
            st.session_state.cesta_aplicacao = [it for it in st.session_state.cesta_aplicacao if it["id"] not in itens_para_remover]
            st.rerun()

        if st.button("➕ Adicionar Nova Linha de Tratamento"):
            st.session_state.cesta_aplicacao.append({
                "id": st.session_state.next_id,
                "matriz": "Fábrica de Ração",
                "produto": lista_produtos[0] if lista_produtos else "",
                "dosagem": 500.0,
                "observacao": "",
                "preco_kg": 15.0,
                "share": 100,
            })
            st.session_state.next_id += 1
            st.rerun()

        df_resumo = pd.DataFrame(resumo_cesta)
        st.subheader("📋 Quadro Consolidado de Consumo e Entrega em ppm")
        st.dataframe(df_resumo, use_container_width=True, hide_index=True)
        st.success(f"📦 **Volume Físico Total Estimado na Conta:** {fmt_br(total_kg_geral, 2)} kg / mês")

    elif modulo == "3. Simulação de Faturamento & Proposta PDF (US$)":
        st.header("Etapa 3: Simulador de Faturamento e Proposta Comercial em PDF (US$)")
        if st.session_state.cliente_nome:
            st.info(f"👤 **Cliente Ativo:** {st.session_state.cliente_nome} (CNPJ: {st.session_state.cliente_cnpj or 'N/A'})")

        matrizes_opcoes = st.session_state.volumes_producao
        linhas_financeiro: List[Dict[str, Any]] = []
        linhas_proposta_pdf: List[Dict[str, Any]] = []
        fat_mensal_total = 0.0
        fat_anual_total = 0.0
        vol_faturado_total = 0.0

        for idx, item in enumerate(st.session_state.cesta_aplicacao):
            vol_base = float(matrizes_opcoes.get(item["matriz"], 0.0))
            dosagem = float(item["dosagem"])
            consumo_kg_100 = (vol_base * dosagem) / 1000.0
            info_p = mapa_produtos.get(item["produto"], {})
            id_prod = str(info_p.get("id_produto", ""))
            entrega = calcular_entrega_ativos(id_prod, dosagem, df_garantias)
            ativos_curto = resumo_curto_ativo_pdf(id_prod, df_garantias)

            c_fin1, c_fin2, c_fin3, c_fin4 = st.columns([3, 2, 2, 3])
            with c_fin1:
                st.markdown(f"**{idx + 1}. {item['produto']}** *(em {item['matriz']})*")
                st.caption(f"Dosagem: {fmt_br(dosagem, 0)} g/ton | {entrega['detalhe_texto']} | Obs: {item.get('observacao') or 'N/A'}")
            with c_fin2:
                item["preco_kg"] = input_numero_br(
                    f"Preço US$/kg (#{idx + 1}):",
                    value=float(item.get("preco_kg", 15.0)),
                    key=f"preco_{item['id']}",
                    casas=2,
                    min_value=0.0,
                )
            with c_fin3:
                item["share"] = st.slider(f"Share % (#{idx + 1}):", min_value=10, max_value=100, value=int(item.get("share", 100)), step=10, key=f"share_{item['id']}")

            preco_kg = float(item["preco_kg"])
            share = int(item["share"])
            consumo_real_kg = consumo_kg_100 * (share / 100.0)
            faturamento_item = consumo_real_kg * preco_kg
            custo_ton_tratada = (dosagem / 1000.0) * preco_kg

            vol_faturado_total += consumo_real_kg
            fat_mensal_total += faturamento_item
            fat_anual_total += faturamento_item * 12.0

            with c_fin4:
                st.metric(
                    label=f"Faturamento Item #{idx + 1}",
                    value=f"US$ {fmt_br(faturamento_item, 2)} /mês",
                    delta=f"Custo Tratamento: US$ {fmt_br(custo_ton_tratada, 2)} /ton",
                )
            st.markdown("---")

            linhas_financeiro.append({
                "Matriz": item["matriz"],
                "Produto": item["produto"],
                "Dosagem (g/ton)": fmt_br(dosagem, 1),
                "Entrega por Molécula": entrega["detalhe_texto"],
                "Observação": item.get("observacao", ""),
                "Custo Tratamento (US$/ton)": fmt_br(custo_ton_tratada, 2),
                "Share (%)": f"{share}%",
                "Volume Faturado (kg/mês)": fmt_br(consumo_real_kg, 2),
                "Preço Unitário (US$/kg)": fmt_br(preco_kg, 2),
                "Faturamento Mensal (US$)": fmt_br(faturamento_item, 2),
                "Faturamento Anual (US$)": fmt_br(faturamento_item * 12.0, 2),
            })

            nome_pdf = f"{item['produto']} ({ativos_curto})" if ativos_curto else item["produto"]
            linhas_proposta_pdf.append({
                "produto_pdf": nome_pdf,
                "dosagem": dosagem,
                "qtd_mensal": consumo_real_kg,
                "preco_kg": preco_kg,
                "custo_ton": custo_ton_tratada,
                "obs_pdf": item.get("observacao", "").strip() or item["matriz"],
            })

        df_fin = pd.DataFrame(linhas_financeiro)
        st.subheader("💼 Resumo Executivo da Conta (US$)")
        st.dataframe(df_fin, use_container_width=True, hide_index=True)

        r1, r2, r3 = st.columns(3)
        r1.metric("Volume Total Faturado (com Share)", f"{fmt_br(vol_faturado_total, 1)} kg/mês")
        r2.metric("Faturamento Mensal Consolidado", f"US$ {fmt_br(fat_mensal_total, 2)}")
        r3.metric("Potencial Anualizado da Conta", f"US$ {fmt_br(fat_anual_total, 2)}")

        st.markdown("---")
        st.subheader("📄 Emissão de Proposta Comercial em PDF (Padrão CFS)")

        modo_proposta = st.radio(
            "Formato da Tabela no PDF:",
            [
                "Comercial Enxuta (Produto, Qtd., Preço, Observação)",
                "Técnica-Comercial (+ Dosagem g/ton e Custo/ton USD)",
            ],
            horizontal=True,
        )
        eh_tecnico = modo_proposta.startswith("Técnica")

        cond1, cond2, cond3, cond4 = st.columns([1.2, 2.3, 1.5, 1.8])
        with cond1:
            st.session_state.incoterm = st.selectbox("Incoterm:", options=["CIF", "FOB"], index=0 if st.session_state.incoterm == "CIF" else 1)
        with cond2:
            st.session_state.destino = st.text_input("Cidade / UF de Destino:", value=st.session_state.destino, placeholder="Ex.: Brasília/DF")
        with cond3:
            st.session_state.expedicao_dias = input_inteiro_br(
                "Expedição (dias úteis):",
                value=int(st.session_state.expedicao_dias),
                key="in_expedicao_dias",
                min_value=1,
                max_value=90,
            )
        with cond4:
            st.session_state.validade_proposta = st.date_input("Validade da proposta:", value=st.session_state.validade_proposta, format="DD/MM/YYYY")

        cond5, cond6 = st.columns([1.5, 3.5])
        with cond5:
            st.session_state.pagamento = st.text_input("Condição de Pagamento:", value=st.session_state.pagamento, placeholder="Ex.: 30 dias")
        with cond6:
            st.session_state.obs_gerais_pdf = st.text_input("Observações Gerais (opcional):", value=st.session_state.obs_gerais_pdf, placeholder="Ex.: Faturamento em BRL pela PTAX venda do dia anterior.")

        pdf_bytes = gerar_pdf_proposta(
            consultor_nome=st.session_state.consultor_nome,
            consultor_email=st.session_state.consultor_email,
            consultor_telefone=st.session_state.consultor_telefone,
            cliente_nome=st.session_state.cliente_nome,
            cliente_cnpj=st.session_state.cliente_cnpj,
            cliente_contato=st.session_state.cliente_contato,
            cliente_email=st.session_state.cliente_email,
            incoterm=st.session_state.incoterm,
            destino=st.session_state.destino,
            expedicao_dias=int(st.session_state.expedicao_dias),
            validade_str=st.session_state.validade_proposta.strftime("%d/%m/%Y"),
            pagamento=st.session_state.pagamento,
            obs_gerais=st.session_state.obs_gerais_pdf,
            modo_tecnico=eh_tecnico,
            linhas_proposta=linhas_proposta_pdf,
        )

        nome_arq_cli = (st.session_state.cliente_nome or "cliente").strip().replace(" ", "_")
        st.download_button(
            label="⬇️ Baixar Proposta Comercial (.PDF)",
            data=pdf_bytes,
            file_name=f"Proposta_Comercial_{nome_arq_cli}_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            type="primary",
        )


if __name__ == "__main__":
    main()
