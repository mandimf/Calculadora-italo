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
    """Gera o PDF da Proposta Comercial com o logo no cabeçalho."""
    pdf = PropostaCFSPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=24)
    pdf.set_margins(15, 14, 15)
    pdf.add_page()

    # Cabeçalho superior: Título + Emissão (Esquerda) e Logo CFS (Direita)
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

    # Blocos FORNECEDOR e CLIENTE lado a lado
    y_info = pdf.get_y()

    # Fornecedor (Esquerda)
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

    # Cliente (Direita)
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
    linha_ac_partes = []
    if cliente_contato.strip():
        linha_ac_partes.append(f"A/C: {cliente_contato.strip()}")
    if cliente_email.strip():
        linha_ac_partes.append(cliente_email.strip())
    if cliente_cnpj.strip():
        linha_ac_partes.append(f"CNPJ: {cliente_cnpj.strip()}")
    pdf.multi_cell(90, 4.5, pdf_safe(" | ".join(linha_ac_partes) or "-
