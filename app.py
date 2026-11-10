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
          "Share de Carteira Pretendido (%)",
          min_value=10,
          max_value=100,
          value=100,
      )

    faturamento_mensal = (
        consumo_sim_kg * preco_venda_kg * (share_carteira / 100.0)
    )
    faturamento_anual = faturamento_mensal * 12.0

    st.markdown("---")
    st.subheader("💰 **Resumo Executivo do Negócio:**")
    f_res1, f_res2 = st.columns(2)
    with f_res1:
      st.metric("Faturamento Potencial Mensal", f"R$ {faturamento_mensal:,.2f}")
    with f_res2:
      st.metric("Faturamento Anualizado", f"R$ {faturamento_anual:,.2f}")
