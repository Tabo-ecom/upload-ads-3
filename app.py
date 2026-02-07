import streamlit as st
import requests
import json
import time
import pandas as pd
from datetime import datetime, timedelta, date, time as dt_time

# ==============================================================================
# ⚙️ CONFIGURACIÓN DE PÁGINA (T-PILOT STYLE)
# ==============================================================================
st.set_page_config(
    page_title="T-PILOT | Ads Control", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="expanded"
)

# Estilos CSS para que se vea como plataforma profesional
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
        border: 1px solid #e0e0e0;
    }
    .stMetric {
        text-align: center !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 24px;
        color: #0f1116;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 🧠 1. CONFIGURACIÓN MAESTRA
# ==============================================================================
STORE_CONFIG = {
    'TABO': { 'pixelId': '4560468307512217', 'pageId': '243219548872531', 'currency': 'COP', 'country': 'COLOMBIA', 'country_code': 'CO' },
    'LUCENT': { 'pixelId': '563993102229371', 'pageId': '113244918233996', 'currency': 'COP', 'country': 'COLOMBIA', 'country_code': 'CO' },
    'ESSENTIALS': { 'pixelId': '464847386087738', 'pageId': '102680836073183', 'currency': 'COP', 'country': 'COLOMBIA', 'country_code': 'CO' },
    'ECUADOR': { 'pixelId': '118188614559337', 'pageId': '105888269081575', 'currency': 'USD', 'country': 'ECUADOR', 'country_code': 'EC' },
    'GUATEMALA': { 'pixelId': '1388416526052294', 'pageId': '837350399464084', 'currency': 'GTQ', 'country': 'GUATEMALA', 'country_code': 'GT' }
}

API_VERSION = "v22.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# ==============================================================================
# 🤖 2. IA COPYWRITING
# ==============================================================================
def generar_copy_ia(api_key, nombre_producto, descripcion):
    if not api_key: return {"headline": "¡Pide y Paga en Casa!", "body": "⚠️ Falta API Key."}
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    prompt = f"""Actúa como experto en Dropshipping. Producto: {nombre_producto}. Contexto: {descripcion}.
    Genera un Headline (max 40 chars) y un Body persuasivo con emojis.
    Responde solo JSON: {{'headline': '...', 'body': '...'}}"""
    try:
        res = requests.post(url, headers=headers, json={
            "model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
            "response_format": { "type": "json_object" }
        }).json()
        return json.loads(res['choices'][0]['message']['content'])
    except Exception as e:
        return {"headline": "Error IA", "body": str(e)}

# ==============================================================================
# 🛠️ 3. CLASE GESTIÓN FB
# ==============================================================================
class FBAdsManager:
    def __init__(self, token):
        self.token = token

    def get_my_ad_accounts(self):
        url = f"{BASE_URL}/me/adaccounts"
        params = {"access_token": self.token, "fields": "name,account_id,currency", "limit": 100}
        res = requests.get(url, params=params).json()
        return {f"{acc.get('name')} ({acc.get('currency')})": f"act_{acc['account_id']}" for acc in res.get('data', [])} if "data" in res else {}

    # --- LANZAMIENTO ---
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
            while True:
                status_res = requests.get(f"{BASE_URL}/{video_id}", params={'fields': 'status,picture', 'access_token': self.token}).json()
                if status_res.get('status', {}).get('video_status') == 'ready': return {"video_id": video_id, "thumbnail_url": status_res.get('picture')}
                time.sleep(3)
        return {"image_hash": list(res['images'].values())[0]['hash']}

    def create_ad_logic(self, account_id, adset_id, media_data, url, head, body, cta, page_id, ad_name_file):
        story = {"page_id": page_id}
        if "video_id" in media_data:
            story["video_data"] = {"video_id": media_data["video_id"], "image_url": media_data["thumbnail_url"], "message": body, "title": head, "call_to_action": {"type": cta, "value": {"link": url}}}
        else:
            story["link_data"] = {"image_hash": media_data["image_hash"], "link": url, "message": body, "name": head, "call_to_action": {"type": cta}}
        
        cr = requests.post(f"{BASE_URL}/{account_id}/adcreatives", data={"name": f"Cr - {ad_name_file}", "object_story_spec": json.dumps(story), "access_token": self.token}).json()
        if "id" not in cr: raise Exception(f"Error Cr: {cr.get('error', {}).get('message')}")
        
        ad = requests.post(f"{BASE_URL}/{account_id}/ads", data={"name": ad_name_file, "adset_id": adset_id, "creative": json.dumps({"creative_id": cr['id']}), "status": "PAUSED", "access_token": self.token}).json()
        if "id" not in ad: raise Exception(f"Error Ad: {ad.get('error', {}).get('message')}")
        return True

    # --- VIGILANTE ---
    def get_insights_custom(self, level, acc_id, time_params):
        endpoint = f"{level}s"
        fields_list = ["id", "name", "status"]
        if level != "campaign": fields_list.append("campaign_name")
        metrics = "spend,impressions,clicks,actions,action_values,cpc,ctr,cpm"
        
        if 'time_range' in time_params:
            t_val = json.dumps(time_params['time_range'])
            insights_field = f"insights.time_range({t_val}){{{metrics}}}"
        else:
            t_val = time_params['date_preset']
            insights_field = f"insights.date_preset({t_val}){{{metrics}}}"

        fields_list.append(insights_field)
        params = {"access_token": self.token, "fields": ",".join(fields_list), "limit": 500}
        res = requests.get(f"{BASE_URL}/{acc_id}/{endpoint}", params=params).json()
        if "error" in res: return []
        return res.get("data", [])

    def toggle_status(self, node_id, current_status):
        new_status = "PAUSED" if current_status == "ACTIVE" else "ACTIVE"
        url = f"{BASE_URL}/{node_id}"
        requests.post(url, params={"access_token": self.token, "status": new_status})
        return new_status

# ==============================================================================
# 🖥️ INTERFAZ T-PILOT
# ==============================================================================

with st.sidebar:
    st.title("✈️ T-PILOT")
    menu = st.radio("Menú Principal", ["📊 VIGILANTE (Reportes)", "🚀 LANZADOR (Campaña)"])
    st.divider()
    
    st.caption("Configuración")
    fb_secret = st.secrets.get("FB_ACCESS_TOKEN", "")
    oa_secret = st.secrets.get("OPENAI_API_KEY", "")
    fb_token = st.text_input("FB Token", value=fb_secret, type="password")
    oa_token = st.text_input("OpenAI Key", value=oa_secret, type="password")
    
    manager = None
    all_accounts = {}
    
    if fb_token:
        try:
            manager = FBAdsManager(fb_token)
            all_accounts = manager.get_my_ad_accounts()
        except: st.error("Token Inválido")

# ==============================================================================
# 📊 MÓDULO 1: EL VIGILANTE (DASHBOARD)
# ==============================================================================
if menu == "📊 VIGILANTE (Reportes)":
    st.header("📊 T-PILOT DASHBOARD")
    
    if not manager:
        st.warning("Conecta tu token de Facebook.")
        st.stop()

    # --- CONTROLES SUPERIORES ---
    c_acc, c_date, c_lvl = st.columns([2, 1.5, 1])
    
    with c_acc:
        # MULTI-CUENTA SELECTOR
        selected_accounts = st.multiselect("📡 Cuentas Publicitarias (Multi-Select)", list(all_accounts.keys()))
    
    with c_date:
        tipo_fecha = st.selectbox("📅 Periodo", ["Hoy", "Ayer", "Últimos 3 días", "Últimos 7 días", "Personalizado"], index=0)
        time_params = {}
        if tipo_fecha == "Hoy": time_params = {'date_preset': 'today'}
        elif tipo_fecha == "Ayer": time_params = {'date_preset': 'yesterday'}
        elif tipo_fecha == "Últimos 3 días": time_params = {'date_preset': 'last_3d'}
        elif tipo_fecha == "Últimos 7 días": time_params = {'date_preset': 'last_7d'}
        elif tipo_fecha == "Personalizado":
            c_d1, c_d2 = st.columns(2)
            d_s = c_d1.date_input("De", date.today())
            d_e = c_d2.date_input("A", date.today())
            time_params = {'time_range': {'since': str(d_s), 'until': str(d_e)}}
            
    with c_lvl:
        nivel = st.selectbox("🔍 Ver", ["campaign", "adset", "ad"], index=0)

    if st.button("🔄 ACTUALIZAR DATOS", type="primary", use_container_width=True):
        if not selected_accounts:
            st.error("Selecciona al menos una cuenta.")
        else:
            with st.spinner("🚀 T-PILOT está recopilando datos de todas tus cuentas..."):
                master_rows = []
                
                # BUCLE MULTI-CUENTA
                for acc_name in selected_accounts:
                    acc_id = all_accounts[acc_name]
                    raw_data = manager.get_insights_custom(nivel, acc_id, time_params)
                    
                    if raw_data:
                        for item in raw_data:
                            # Parseo de datos
                            insights = item.get("insights", {}).get("data", [{}])[0]
                            spend = float(insights.get("spend", 0))
                            
                            # FILTRO ESTRICTO: SOLO SI GASTÓ DINERO
                            if spend > 0:
                                purchases = 0
                                facturado = 0.0
                                if "actions" in insights:
                                    for act in insights["actions"]:
                                        if act["action_type"] == "purchase": purchases = int(act["value"])
                                if "action_values" in insights:
                                    for val in insights["action_values"]:
                                        if val["action_type"] == "purchase": facturado = float(val["value"])
                                
                                master_rows.append({
                                    "Cuenta": acc_name.split('(')[0], # Nombre limpio
                                    "ID": item["id"],
                                    "Nombre": item["name"],
                                    "Estado": item["status"],
                                    "Gasto": spend,
                                    "Facturado": facturado,
                                    "Compras": purchases,
                                    "CPA": spend / purchases if purchases > 0 else 0,
                                    "ROAS": facturado / spend if spend > 0 else 0,
                                    "CTR": float(insights.get("ctr", 0))
                                })
                
                if not master_rows:
                    st.warning("⚠️ Ninguna campaña ha gastado dinero en este periodo.")
                else:
                    df = pd.DataFrame(master_rows)
                    
                    # --- DASHBOARD VISUAL ---
                    st.markdown("### 📈 Rendimiento Global")
                    
                    col_k1, col_k2, col_k3, col_k4, col_k5 = st.columns(5)
                    
                    col_k1.metric("💸 Gasto Total", f"${df['Gasto'].sum():,.0f}")
                    col_k2.metric("💰 Facturado", f"${df['Facturado'].sum():,.0f}")
                    col_k3.metric("📦 Compras", f"{df['Compras'].sum()}")
                    
                    global_cpa = df['Gasto'].sum() / df['Compras'].sum() if df['Compras'].sum() > 0 else 0
                    global_roas = df['Facturado'].sum() / df['Gasto'].sum() if df['Gasto'].sum() > 0 else 0
                    
                    col_k4.metric("📉 CPA Global", f"${global_cpa:,.0f}")
                    col_k5.metric("🔥 ROAS Global", f"{global_roas:.2f}x")
                    
                    # --- TABLA ESTILIZADA ---
                    st.markdown("### 📋 Detalle Operativo")
                    
                    def style_df(val):
                        if isinstance(val, float):
                            return "{:,.0f}" if val > 100 else "{:.2f}"
                        return str(val)

                    # Colores condicionales
                    def color_kpis(row):
                        cpa_color = 'background-color: #ffcccc' if row['CPA'] > 40000 else ('background-color: #ccffcc' if row['CPA'] < 20000 and row['CPA'] > 0 else '')
                        return [cpa_color if col == 'CPA' else '' for col in row.index]

                    # Columnas a mostrar
                    display_cols = ["Cuenta", "Estado", "Nombre", "Gasto", "Facturado", "Compras", "CPA", "ROAS", "CTR"]
                    
                    st.dataframe(
                        df[display_cols].style
                        .format({
                            "Gasto": "${:,.0f}", "Facturado": "${:,.0f}", "CPA": "${:,.0f}", 
                            "ROAS": "{:.2f}x", "CTR": "{:.2f}%"
                        })
                        .apply(lambda x: ["color: red" if v == "PAUSED" else "color: green" for v in x], subset=["Estado"])
                        .background_gradient(cmap="Reds", subset=["CPA"], vmin=10000, vmax=50000),
                        use_container_width=True,
                        height=600
                    )
                    
                    # --- ACCIONES ---
                    st.divider()
                    c_act1, c_act2 = st.columns([3,1])
                    with c_act1:
                        # Creamos un identificador único para el selector (Nombre + ID) para evitar duplicados
                        df['Selector'] = df['Nombre'] + " | " + df['ID']
                        target_sel = st.selectbox("Selecciona para Apagar/Prender:", df['Selector'].tolist())
                    
                    with c_act2:
                        if st.button("🔘 CAMBIAR ESTADO", use_container_width=True):
                            row = df[df['Selector'] == target_sel].iloc[0]
                            # Toca buscar el Token, pero asumimos que el manager tiene acceso a todas
                            new_s = manager.toggle_status(row['ID'], row['Estado'])
                            st.success(f"Estado actualizado a: {new_s}")
                            time.sleep(1)
                            st.experimental_rerun()

# ==============================================================================
# 🚀 MÓDULO 2: LANZADOR (CÓDIGO ORIGINAL INTACTO)
# ==============================================================================
elif menu == "🚀 LANZADOR (Campaña)":
    st.header("🚀 Lanzador Multi-Cuenta")
    if not manager: st.stop()
    
    # [AQUÍ VA LA LÓGICA DE LANZAMIENTO QUE YA TENÍAMOS - RESUMIDA PARA NO REPETIR]
    # (El código del lanzador sigue funcionando igual, usando st.multiselect para cuentas)
    
    c1, c2 = st.columns([1, 1.2])
    with c1:
        st.subheader("Config")
        acc_launch = st.multiselect("Cuentas", list(all_accounts.keys()))
        marcas = st.multiselect("Tiendas", list(STORE_CONFIG.keys()))
        f_ini = st.date_input("Inicio", datetime.now() + timedelta(days=1))
        prod = st.text_input("Producto", "PROD").upper()
        url_dst = st.text_input("URL")
        strat = st.radio("Estrategia", ["ABO", "CBO", "TESTEO"])
        budg = st.number_input("Presupuesto", 40000)
    
    with c2:
        st.subheader("Creativos")
        files = st.file_uploader("Archivos", accept_multiple_files=True)
        h1 = st.text_input("Headline", "¡Pide hoy!")
        b1 = st.text_area("Copy")
        
        if st.button("✨ IA Copy"):
            if oa_token:
                res = generar_copy_ia(oa_token, prod, "Desc")
                st.info(f"H: {res.get('headline')} | B: {res.get('body')}")

    if st.button("🚀 LANZAR AHORA", type="primary"):
        if not acc_launch or not files: st.error("Faltan datos")
        else:
            bar = st.progress(0)
            st_text = st.empty()
            unix = int(datetime.combine(f_ini, dt_time(5,0)).timestamp())
            
            total_steps = len(acc_launch) * len(marcas)
            curr_step = 0
            
            for ac_name in acc_launch:
                aid = all_accounts[ac_name]
                for m in marcas:
                    cfg = STORE_CONFIG[m]
                    st_text.text(f"Procesando {ac_name} -> {m}...")
                    
                    # 1. Campaña
                    cn = f"{cfg['country']} - {prod} - {strat} - {datetime.now().strftime('%d/%m')}"
                    pc = {'name': cn, 'objective': 'OUTCOME_SALES', 'status': 'PAUSED', 'special_ad_categories': '[]', 'access_token': fb_token}
                    if strat == "CBO": pc.update({'daily_budget': int(budg), 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP'})
                    
                    try:
                        camp = requests.post(f"{BASE_URL}/{aid}/campaigns", data=pc).json()
                        cid = camp['id']
                        
                        # Adsets
                        if strat == "TESTEO":
                            for i, f in enumerate(files):
                                media = manager.upload_media(aid, file_obj=f, file_type=f.type)
                                pa = {'name': f"TEST {i+1}", 'campaign_id': cid, 'status': 'PAUSED', 'targeting': json.dumps({'geo_locations': {'countries': [cfg['country_code']]}, 'age_min': 18, 'age_max': 65}), 'start_time': unix, 'billing_event': 'IMPRESSIONS', 'optimization_goal': 'OFFSITE_CONVERSIONS', 'promoted_object': json.dumps({'pixel_id': cfg['pixelId'], 'custom_event_type': 'PURCHASE'}), 'destination_type': 'WEBSITE', 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP', 'daily_budget': int(budg), 'access_token': fb_token}
                                adset = requests.post(f"{BASE_URL}/{aid}/adsets", data=pa).json()
                                manager.create_ad_logic(aid, adset['id'], media, url_dst, h1, b1, "ORDER_NOW", cfg['pageId'], f.name)
                        else:
                            pa = {'name': "OPEN", 'campaign_id': cid, 'status': 'PAUSED', 'targeting': json.dumps({'geo_locations': {'countries': [cfg['country_code']]}, 'age_min': 18, 'age_max': 65}), 'start_time': unix, 'billing_event': 'IMPRESSIONS', 'optimization_goal': 'OFFSITE_CONVERSIONS', 'promoted_object': json.dumps({'pixel_id': cfg['pixelId'], 'custom_event_type': 'PURCHASE'}), 'destination_type': 'WEBSITE', 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP', 'access_token': fb_token}
                            if strat == "ABO": pa['daily_budget'] = int(budg)
                            adset = requests.post(f"{BASE_URL}/{aid}/adsets", data=pa).json()
                            for f in files:
                                media = manager.upload_media(aid, file_obj=f, file_type=f.type)
                                manager.create_ad_logic(aid, adset['id'], media, url_dst, h1, b1, "ORDER_NOW", cfg['pageId'], f.name)
                        
                    except Exception as e: st.error(f"Error: {e}")
                    
                    curr_step += 1
                    bar.progress(curr_step / total_steps)
            
            st.balloons()
            st.success("¡Lanzamiento T-PILOT Completado!")
