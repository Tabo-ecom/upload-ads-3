import streamlit as st
import requests
import json
import time
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta, date, time as dt_time

# ==============================================================================
# ⚙️ CONFIGURACIÓN DE PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="T-PILOT | Ads Control Center", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="expanded"
)

# Estilos CSS Profesionales + Semáforos
st.markdown("""
<style>
    .metric-card {
        background-color: #ffffff;
        border-radius: 8px;
        padding: 15px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border-left: 5px solid #4F8BF9;
    }
    .stMetric { text-align: center !important; }
    /* Ajustes para tablas */
    .stDataFrame { font-size: 14px; }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 🧠 1. CONFIGURACIÓN MAESTRA & BASE DE DATOS
# ==============================================================================
STORE_CONFIG = {
    'TABO': { 'pixelId': '4560468307512217', 'pageId': '243219548872531', 'currency': 'COP', 'country': 'COLOMBIA', 'country_code': 'CO' },
    'LUCENT': { 'pixelId': '563993102229371', 'pageId': '113244918233996', 'currency': 'COP', 'country': 'COLOMBIA', 'country_code': 'CO' },
    'ECUADOR': { 'pixelId': '118188614559337', 'pageId': '105888269081575', 'currency': 'USD', 'country': 'ECUADOR', 'country_code': 'EC' },
}

API_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# --- DATABASE LOCAL (Winners Library) ---
def init_db():
    conn = sqlite3.connect('tpilot_winners.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS winners 
                 (id INTEGER PRIMARY KEY, creative_id TEXT, image_hash TEXT, name TEXT, roas REAL, date_added TEXT)''')
    conn.commit()
    conn.close()

def save_winner(creative_id, image_hash, name, roas):
    conn = sqlite3.connect('tpilot_winners.db')
    c = conn.cursor()
    c.execute("INSERT INTO winners (creative_id, image_hash, name, roas, date_added) VALUES (?, ?, ?, ?, ?)",
              (creative_id, image_hash, name, roas, str(date.today())))
    conn.commit()
    conn.close()

def get_winners():
    conn = sqlite3.connect('tpilot_winners.db')
    df = pd.read_sql_query("SELECT * FROM winners ORDER BY roas DESC", conn)
    conn.close()
    return df

init_db()

# ==============================================================================
# 🛠️ 2. LOGICA DE NEGOCIO (SEMAFOROS & FATIGA)
# ==============================================================================

def apply_stoplight_style(df):
    """Aplica colores condicionales al DataFrame"""
    def style_row(row):
        # Definir Umbrales (Ejemplo en Pesos Colombianos, ajustar si es USD)
        CPA_LIMIT = 50000 
        ROAS_MIN = 1.0
        ROAS_TARGET = 3.0
        
        # Lógica ROAS
        roas_style = ''
        if row['ROAS'] < ROAS_MIN: roas_style = 'background-color: #ffcccc; color: black;' # Rojo Kill
        elif row['ROAS'] > ROAS_TARGET: roas_style = 'background-color: #ccffcc; color: black;' # Verde Scale
        else: roas_style = 'background-color: #ffffcc; color: black;' # Amarillo Monitor
        
        # Lógica CPA
        cpa_style = ''
        if row['CPA'] > CPA_LIMIT: cpa_style = 'background-color: #ffcccc; color: black;'
        elif row['CPA'] < (CPA_LIMIT * 0.6): cpa_style = 'background-color: #ccffcc; color: black;'
        
        # Lógica Fatiga
        fatigue_style = ''
        if row.get('Fatiga') == '⚠️ ALERTA': fatigue_style = 'background-color: #ffeb3b; font-weight: bold; color: black;'

        styles = ['' for _ in row.index]
        # Mapear estilos a columnas específicas
        if 'ROAS' in row.index: styles[df.columns.get_loc('ROAS')] = roas_style
        if 'CPA' in row.index: styles[df.columns.get_loc('CPA')] = cpa_style
        if 'Fatiga' in row.index: styles[df.columns.get_loc('Fatiga')] = fatigue_style
        
        return styles

    return df.style.apply(style_row, axis=1).format({
        "Gasto": "${:,.0f}", "Ventas": "${:,.0f}", "CPA": "${:,.0f}", 
        "ROAS": "{:.2f}x", "CTR": "{:.2f}%", "Frecuencia": "{:.2f}"
    })

# ==============================================================================
# 🛠️ 3. CLASE GESTIÓN FB (UPDATED)
# ==============================================================================
class FBAdsManager:
    def __init__(self, token):
        self.token = token

    def get_my_ad_accounts(self):
        url = f"{BASE_URL}/me/adaccounts"
        params = {"access_token": self.token, "fields": "name,account_id,currency", "limit": 100}
        res = requests.get(url, params=params).json()
        return {f"{acc.get('name')}": f"act_{acc['account_id']}" for acc in res.get('data', [])} if "data" in res else {}

    def get_insights(self, level, acc_id, time_params, parent_id=None):
        """Obtiene métricas. Si hay parent_id, filtra (Drill-down)."""
        endpoint = f"{acc_id}/insights"
        fields = "campaign_name,adset_name,ad_name,spend,purchase_roas,actions,action_values,cpc,ctr,frequency,impressions"
        
        # Identificadores necesarios para el drill-down
        id_fields = "campaign_id,adset_id,ad_id"
        
        params = {
            "access_token": self.token,
            "level": level,
            "fields": f"{id_fields},{fields}",
            "limit": 500
        }
        
        # Filtros para Drill-Down
        filtering = []
        if level == 'adset' and parent_id:
            filtering.append({'field': 'campaign.id', 'operator': 'EQUAL', 'value': parent_id})
        elif level == 'ad' and parent_id:
            filtering.append({'field': 'adset.id', 'operator': 'EQUAL', 'value': parent_id})
        
        if filtering:
            params['filtering'] = json.dumps(filtering)

        if 'time_range' in time_params:
            params['time_range'] = json.dumps(time_params['time_range'])
        else:
            params['date_preset'] = time_params['date_preset']

        res = requests.get(f"{BASE_URL}/{endpoint}", params=params).json()
        return res.get("data", [])

    def get_daily_trend(self, acc_id):
        """Para el gráfico de líneas (Últimos 7 días)"""
        url = f"{BASE_URL}/{acc_id}/insights"
        params = {
            "access_token": self.token,
            "level": "account",
            "fields": "spend,purchase_roas,ctr,date_start",
            "date_preset": "last_7d",
            "time_increment": 1
        }
        res = requests.get(url, params=params).json()
        return res.get("data", [])

    def get_ad_creative_preview(self, ad_id):
        """Obtiene la imagen del anuncio para el panel visual"""
        url = f"{BASE_URL}/{ad_id}"
        params = {"access_token": self.token, "fields": "adcreatives{image_url,thumbnail_url}"}
        res = requests.get(url, params=params).json()
        try:
            creatives = res.get('adcreatives', {}).get('data', [])
            if creatives:
                return creatives[0].get('image_url') or creatives[0].get('thumbnail_url')
        except:
            return None
        return None
    
    # ... (Funciones de upload_media y create_ad se mantienen igual que tu código anterior)
    def upload_media(self, ad_account_id, file_obj=None, file_url=None, file_type="image/jpeg"):
        endpoint = "advideos" if "video" in file_type else "adimages"
        url = f"{BASE_URL}/{ad_account_id}/{endpoint}"
        params = {'access_token': self.token}
        if file_obj:
            file_obj.seek(0)
            files = {'file': (file_obj.name, file_obj.read(), file_obj.type)}
            res = requests.post(url, params=params, files=files).json()
        elif file_url:
            params['url'] = file_url 
            res = requests.post(url, params=params).json()
        
        if "error" in res: raise Exception(f"Media Error: {res['error'].get('message')}")
        
        if "video" in file_type:
            video_id = res['id']
            # Espera simple para video ready
            time.sleep(2) 
            return {"video_id": video_id}
        return {"image_hash": list(res['images'].values())[0]['hash']}

# ==============================================================================
# 🖥️ INTERFAZ PRINCIPAL
# ==============================================================================

with st.sidebar:
    st.title("✈️ T-PILOT")
    st.markdown("---")
    menu = st.radio("Navegación", ["📊 VIGILANTE (Cockpit)", "🚀 LANZADOR (Builder)"])
    st.markdown("---")
    
    fb_token = st.text_input("FB Token", type="password")
    
    manager = None
    all_accounts = {}
    
    if fb_token:
        try:
            manager = FBAdsManager(fb_token)
            all_accounts = manager.get_my_ad_accounts()
            current_account_name = st.selectbox("Cuenta Activa", list(all_accounts.keys()))
            current_account_id = all_accounts[current_account_name]
        except: st.error("Token Inválido")

# ==============================================================================
# 📊 MÓDULO 1: EL VIGILANTE (DRILL-DOWN & SEMAFOROS)
# ==============================================================================
if menu == "📊 VIGILANTE (Cockpit)":
    if not manager: st.stop()

    st.markdown("## 🕹️ Cockpit de Control")

    # 1. HEADER (KPIs GLOBAL)
    # ---------------------------------------------------------
    time_preset = st.selectbox("📅 Tiempo", ["today", "yesterday", "last_3d", "last_7d"], index=0)
    
    # Traemos datos globales de la cuenta
    with st.spinner("Analizando cuenta..."):
        acc_data = manager.get_insights("account", current_account_id, {'date_preset': time_preset})
        daily_trend = manager.get_daily_trend(current_account_id)

    if acc_data:
        data = acc_data[0]
        spend = float(data.get('spend', 0))
        # Calcular ROAS y Ventas manual (handling different response formats)
        roas = 0
        val_compras = 0
        purchases = 0
        if 'purchase_roas' in data: roas = float(data['purchase_roas'][0]['value'])
        if 'action_values' in data: 
            for x in data['action_values']: 
                if x['action_type'] == 'purchase': val_compras = float(x['value'])
        if 'actions' in data:
            for x in data['actions']:
                if x['action_type'] == 'purchase': purchases = int(x['value'])
        
        cpa = spend / purchases if purchases > 0 else 0

        # Render Header
        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(f"<div class='metric-card'><h3>💸 Gasto</h3><h2>${spend:,.0f}</h2></div>", unsafe_allow_html=True)
        k2.markdown(f"<div class='metric-card'><h3>📦 Ventas (Val)</h3><h2>${val_compras:,.0f}</h2></div>", unsafe_allow_html=True)
        k3.markdown(f"<div class='metric-card'><h3>📉 CPA</h3><h2>${cpa:,.0f}</h2></div>", unsafe_allow_html=True)
        color_roas = "green" if roas >= 2 else "red"
        k4.markdown(f"<div class='metric-card'><h3>🔥 ROAS</h3><h2 style='color:{color_roas}'>{roas:.2f}x</h2></div>", unsafe_allow_html=True)

    # 2. TREND GRAPH (Fatiga Visual)
    # ---------------------------------------------------------
    st.markdown("### 📈 Tendencia: Gasto vs ROAS vs CTR")
    if daily_trend:
        df_trend = pd.DataFrame(daily_trend)
        df_trend['spend'] = df_trend['spend'].astype(float)
        df_trend['ctr'] = df_trend['ctr'].astype(float)
        # Fix ROAS parsing safely
        df_trend['roas'] = df_trend['purchase_roas'].apply(lambda x: float(x[0]['value']) if isinstance(x, list) else 0)
        
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df_trend['date_start'], y=df_trend['spend'], name='Gasto ($)', marker_color='#E0E0E0'))
        fig.add_trace(go.Scatter(x=df_trend['date_start'], y=df_trend['roas'], name='ROAS', yaxis='y2', line=dict(color='green', width=3)))
        fig.add_trace(go.Scatter(x=df_trend['date_start'], y=df_trend['ctr'], name='CTR (%)', yaxis='y2', line=dict(color='blue', dash='dot')))
        
        fig.update_layout(
            yaxis=dict(title="Gasto"),
            yaxis2=dict(title="ROAS / CTR", overlaying='y', side='right'),
            legend=dict(orientation="h", y=1.1),
            margin=dict(l=0, r=0, t=30, b=0),
            height=300
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # 3. DRILL-DOWN (SEMAFORO)
    # ---------------------------------------------------------
    st.subheader("🕵️ Profundización (Drill-Down)")

    # NIVEL 1: CAMPAÑAS
    raw_camps = manager.get_insights("campaign", current_account_id, {'date_preset': time_preset})
    
    def process_data(raw_list, level_name):
        rows = []
        for item in raw_list:
            spend = float(item.get('spend', 0))
            if spend == 0: continue # Ocultar lo que no gasta
            
            purchases = 0
            val_compras = 0
            roas = 0
            if 'actions' in item:
                for x in item['actions']: 
                    if x['action_type'] == 'purchase': purchases = int(x['value'])
            if 'action_values' in item:
                for x in item['action_values']:
                    if x['action_type'] == 'purchase': val_compras = float(x['value'])
            
            cpa = spend / purchases if purchases > 0 else 0
            roas = val_compras / spend if spend > 0 else 0
            ctr = float(item.get('ctr', 0))
            freq = float(item.get('frequency', 0))
            
            # Detección de Fatiga
            fatiga_status = "OK"
            if freq > 2.5 and ctr < 1.0: # Umbral de ejemplo
                fatiga_status = "⚠️ ALERTA"

            row = {
                "ID": item[f'{level_name}_id'],
                "Nombre": item[f'{level_name}_name'],
                "Gasto": spend,
                "Ventas": val_compras,
                "CPA": cpa,
                "ROAS": roas,
                "CTR": ctr,
                "Frecuencia": freq,
                "Fatiga": fatiga_status
            }
            rows.append(row)
        return pd.DataFrame(rows)

    df_camps = process_data(raw_camps, "campaign")
    
    if not df_camps.empty:
        # Selección de Campaña
        st.markdown("#### 1️⃣ Campañas")
        
        # Evento de Selección en Dataframe (Streamlit moderno)
        event = st.dataframe(
            apply_stoplight_style(df_camps),
            on_select="rerun",
            selection_mode="single-row",
            use_container_width=True,
            hide_index=True
        )
        
        # Lógica Drill-Down
        selected_campaign_id = None
        if len(event.selection.rows) > 0:
            idx = event.selection.rows[0]
            selected_campaign_id = df_camps.iloc[idx]["ID"]
            st.info(f"Analizando Campaña: {df_camps.iloc[idx]['Nombre']}")

            # NIVEL 2: ADSETS
            if selected_campaign_id:
                raw_adsets = manager.get_insights("adset", current_account_id, {'date_preset': time_preset}, parent_id=selected_campaign_id)
                df_adsets = process_data(raw_adsets, "adset")
                
                st.markdown("#### 2️⃣ Conjuntos de Anuncios")
                event_adset = st.dataframe(
                    apply_stoplight_style(df_adsets),
                    on_select="rerun",
                    selection_mode="single-row",
                    use_container_width=True,
                    hide_index=True
                )

                # NIVEL 3: ANUNCIOS (CREATIVOS)
                if len(event_adset.selection.rows) > 0:
                    idx_adset = event_adset.selection.rows[0]
                    selected_adset_id = df_adsets.iloc[idx_adset]["ID"]
                    
                    raw_ads = manager.get_insights("ad", current_account_id, {'date_preset': time_preset}, parent_id=selected_adset_id)
                    df_ads = process_data(raw_ads, "ad")
                    
                    st.markdown("#### 3️⃣ Anuncios (Creativos)")
                    
                    # Mostrar tabla de anuncios con alerta de fatiga
                    st.dataframe(apply_stoplight_style(df_ads), use_container_width=True, hide_index=True)
                    
                    # GALERÍA VISUAL DE GANADORES
                    st.markdown("##### 🖼️ Galería Visual")
                    cols = st.columns(4)
                    for i, row in df_ads.iterrows():
                        with cols[i % 4]:
                            # Intentar obtener preview
                            img_url = manager.get_ad_creative_preview(row['ID'])
                            if img_url:
                                st.image(img_url, use_column_width=True)
                            st.caption(f"**{row['Nombre']}**")
                            st.caption(f"ROAS: {row['ROAS']:.2f} | CTR: {row['CTR']:.2f}%")
                            
                            # Botón para guardar en Librería de Ganadores
                            if row['ROAS'] > 2.5:
                                if st.button(f"🏆 Guardar Ganador", key=f"save_{row['ID']}"):
                                    # Aquí idealmente buscaríamos el creative_id real y el hash
                                    # Por simplicidad, guardamos el ID del anuncio como referencia
                                    save_winner(row['ID'], "HASH_PENDING", row['Nombre'], row['ROAS'])
                                    st.toast("¡Guardado en Librería!")


# ==============================================================================
# 🚀 MÓDULO 2: LANZADOR (BUILDER & NAMING)
# ==============================================================================
elif menu == "🚀 LANZADOR (Builder)":
    if not manager: st.stop()

    st.markdown("## 🏗️ Constructor de Campañas")

    # 1. NAMING CONVENTION GENERATOR
    # ---------------------------------------------------------
    with st.expander("🏷️ Naming Convention (Estándar)", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        n_country = c1.selectbox("País", ["COL", "ECU", "GUA", "USA"])
        n_type = c2.selectbox("Tipo", ["CBO", "ABO", "TEST"])
        n_prod = c3.text_input("Producto (Clave)", "MASCARILLA").upper()
        n_buyer = c4.text_input("Media Buyer", "TB").upper()
        
        final_name = f"[{n_country}] - [{n_type}] - [{n_prod}] - [{date.today().strftime('%d/%m')}] - [{n_buyer}]"
        st.code(final_name, language="text")

    # 2. SELECCIÓN DE CREATIVOS (LIBRERÍA O SUBIDA)
    # ---------------------------------------------------------
    st.subheader("🎨 Creativos")
    
    tab_upload, tab_library = st.tabs(["📤 Subir Nuevos", "🏆 Librería de Ganadores"])
    
    files_to_launch = [] # Lista final de archivos/hashes para lanzar
    
    with tab_upload:
        uploaded_files = st.file_uploader("Archivos Locales", accept_multiple_files=True)
        if uploaded_files: files_to_launch = uploaded_files

    with tab_library:
        df_winners = get_winners()
        if not df_winners.empty:
            st.dataframe(df_winners)
            selected_winners = st.multiselect("Reutilizar estos ganadores:", df_winners['name'].tolist())
            if selected_winners:
                st.info(f"Se usarán {len(selected_winners)} creativos ganadores (Lógica de hash pendiente de integración completa).")
                # Aquí en producción recuperarías el hash real de la DB
        else:
            st.info("Aún no has guardado ganadores desde el Vigilante.")

    # 3. CONFIG FINAL
    # ---------------------------------------------------------
    st.divider()
    c_conf1, c_conf2 = st.columns(2)
    with c_conf1:
        launch_acc = st.multiselect("Cuentas Destino", list(all_accounts.keys()))
        launch_store = st.selectbox("Config Tienda", list(STORE_CONFIG.keys()))
    with c_conf2:
        launch_budget = st.number_input("Presupuesto Diario", 50000)
        launch_copy = st.text_area("Copy Principal")
        launch_headline = st.text_input("Headline", "¡Oferta Limitada!")

    if st.button("🚀 LANZAR CAMPAÑA OFICIAL", type="primary", use_container_width=True):
        st.success(f"Lanzando campaña: **{final_name}**")
        st.write("Simulación de envío a API...")
        # Aquí iría la llamada a create_campaign usando final_name y los archivos
        time.sleep(2)
        st.balloons()
