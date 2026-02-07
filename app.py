import pandas as pd # No olvides importar pandas al inicio del archivo

# ... (Todo tu código de configuración y clases sigue igual arriba) ...

# ==============================================================================
# 🖥️ 4. INTERFAZ STREAMLIT (CON EL VIGILANTE)
# ==============================================================================
st.set_page_config(page_title="GL Ads Suite", layout="wide", page_icon="⚡")

# --- LOGIN / TOKENS ---
fb_secret = st.secrets.get("FB_ACCESS_TOKEN", "")
oa_secret = st.secrets.get("OPENAI_API_KEY", "")

with st.sidebar:
    st.title("⚡ GL Suite")
    
    # MENÚ DE NAVEGACIÓN
    menu = st.radio("Menú", ["🚀 Lanzador", "👁️ El Vigilante (Analytics)"])
    st.divider()
    
    st.header("🔑 Accesos")
    fb_token = st.text_input("FB Token", value=fb_secret, type="password")
    oa_token = st.text_input("OpenAI Key", value=oa_secret, type="password")
    
    ad_account_id = None
    manager = None
    if fb_token:
        try:
            manager = FBAdsManager(fb_token)
            accounts = manager.get_my_ad_accounts()
            if accounts:
                acc_name = st.selectbox("Cuenta Activa", list(accounts.keys()))
                ad_account_id = accounts[acc_name]
        except: st.error("Token FB Error")

if not ad_account_id: st.stop()

# ==============================================================================
# 🚀 MÓDULO 1: EL LANZADOR (TU CÓDIGO ORIGINAL)
# ==============================================================================
if menu == "🚀 Lanzador":
    st.title("🚀 Lanzador de Campañas")
    # ... (AQUÍ PEGAS TODO EL CÓDIGO DE TU INTERFAZ DE LANZAMIENTO ANTERIOR) ...
    # ... (Si quieres te paso el archivo completo unido, pero es básicamente tu código previo aquí)
    st.info("ℹ️ Aquí va tu interfaz de lanzamiento (Campaña, Creativos, IA, etc).") 
    # [PARA MANTENER EL MENSAJE CORTO, ASUMO QUE MANTIENES TU CÓDIGO AQUÍ]

# ==============================================================================
# 👁️ MÓDULO 2: EL VIGILANTE (NUEVO)
# ==============================================================================
elif menu == "👁️ El Vigilante (Analytics)":
    st.title(f"👁️ El Vigilante: {acc_name}")
    
    # 1. Filtros
    col_f1, col_f2 = st.columns(2)
    rango_fecha = col_f1.selectbox("📅 Rango de Fechas", ["maximum", "today", "yesterday", "last_3d", "last_7d", "last_30d"], index=2)
    nivel = col_f2.selectbox("🔍 Nivel de Análisis", ["campaign", "adset", "ad"], index=0)
    
    if st.button("🔄 Analizar Datos"):
        with st.spinner("Conectando con Facebook Intelligence..."):
            data = manager.get_insights(nivel, ad_account_id, date_preset=rango_fecha)
            
            if not data:
                st.warning("No hay datos para este periodo.")
            else:
                # 2. Procesamiento de Datos con Pandas
                rows = []
                for item in data:
                    # Extraer Compras y Valor de compras del JSON complejo de FB
                    purchases = 0
                    purchases_value = 0.0
                    
                    if "actions" in item:
                        for act in item["actions"]:
                            if act["action_type"] == "purchase": purchases = int(act["value"])
                    
                    if "action_values" in item:
                        for val in item["action_values"]:
                            if val["action_type"] == "purchase": purchases_value = float(val["value"])
                    
                    spend = float(item.get("spend", 0))
                    
                    # Cálculos KPIs
                    roas = round(purchases_value / spend, 2) if spend > 0 else 0
                    cpa = round(spend / purchases, 0) if purchases > 0 else 0
                    cpm = float(item.get("cpm", 0))
                    ctr = float(item.get("ctr", 0))
                    
                    row = {
                        "ID": item["id"],
                        "Estado": item.get("status", "UNKNOWN"), # ACTIVE / PAUSED
                        "Nombre": item["name"],
                        "Gasto": spend,
                        "Ventas": purchases,
                        "ROAS": roas,
                        "CPA": cpa,
                        "CTR %": ctr,
                        "CPM": cpm
                    }
                    rows.append(row)
                
                df = pd.DataFrame(rows)
                
                # 3. Visualización de Métricas (KPIs Generales)
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Gasto Total", f"${df['Gasto'].sum():,.0f}")
                k2.metric("Ventas Totales", f"{df['Ventas'].sum()}")
                total_roas = round(df['Ventas'].sum() * df['CPA'].mean() / df['Gasto'].sum(), 2) if df['Gasto'].sum() > 0 else 0 
                # (Nota: ROAS promedio simple para visualización rápida)
                k3.metric("ROAS Promedio (Est)", f"{df['ROAS'].mean():.2f}") 
                k4.metric("CPA Promedio", f"${df['CPA'].mean():,.0f}")

                st.divider()
                
                # 4. Tabla Interactiva (Dataframe)
                # Colorear CPA alto (Malo > 30.000, Bueno < 15.000 - Ejemplo)
                def color_cpa(val):
                    color = 'red' if val > 40000 else ('green' if val > 0 and val < 20000 else 'black')
                    return f'color: {color}'
                
                st.subheader("📊 Tabla de Rendimiento")
                
                # Mostramos la tabla. Editamos configuración para que se vea bien
                st.dataframe(
                    df.style.applymap(color_cpa, subset=['CPA'])
                    .format({"Gasto": "${:,.0f}", "CPA": "${:,.0f}", "ROAS": "{:.2f}x", "CTR %": "{:.2f}%"}),
                    use_container_width=True,
                    height=500
                )
                
                # 5. TOMAR ACCIÓN (El verdadero "Vigilante")
                st.subheader("👮‍♂️ Centro de Control")
                col_c1, col_c2 = st.columns([2, 1])
                
                with col_c1:
                    ad_to_change = st.selectbox("Selecciona para Apagar/Prender:", df['Nombre'].tolist())
                
                with col_c2:
                    if st.button("🚨 Cambiar Estado (ON/OFF)"):
                        # Buscar ID
                        id_target = df[df['Nombre'] == ad_to_change]['ID'].values[0]
                        status_now = df[df['Nombre'] == ad_to_change]['Estado'].values[0]
                        
                        # Llamar a la API
                        new_st = manager.toggle_status(id_target, status_now)
                        st.success(f"✅ {ad_to_change} ahora está: {new_st}")
                        time.sleep(1)
                        st.experimental_rerun() # Recargar página
