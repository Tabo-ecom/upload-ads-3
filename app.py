import streamlit as st  # <--- ESTA LÍNEA DEBE SER LA PRIMERA
import requests
import json
import time
import pandas as pd
from datetime import datetime, timedelta, time as dt_time

# ==============================================================================
# ⚙️ CONFIGURACIÓN DE PÁGINA (DEBE IR AQUÍ, AL PRINCIPIO)
# ==============================================================================
st.set_page_config(
    page_title="GL Ads Suite", 
    layout="wide", 
    page_icon="⚡"
)

# ==============================================================================
# 🧠 1. CONFIGURACIÓN MAESTRA (Tus Tiendas)
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
# 🤖 2. AGENTE DE IA (Generador de Copy)
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
# 🛠️ 3. CLASE DE GESTIÓN FACEBOOK (Lanzador + Vigilante)
# ==============================================================================
class FBAdsManager:
    def __init__(self, token):
        self.token = token

    def get_my_ad_accounts(self):
        url = f"{BASE_URL}/me/adaccounts"
        params = {"access_token": self.token, "fields": "name,account_id,currency", "limit": 100}
        res = requests.get(url, params=params).json()
        return {f"{acc.get('name')} ({acc.get('currency')})": f"act_{acc['account_id']}" for acc in res.get('data', [])} if "data" in res else {}

    # --- FUNCIONES DE LANZAMIENTO ---
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
                status = status_res.get('status', {}).get('video_status')
                if status == 'ready': return {"video_id": video_id, "thumbnail_url": status_res.get('picture')}
                if status == 'error': raise Exception("FB rechazó el video.")
                time.sleep(3)
        return {"image_hash": list(res['images'].values())[0]['hash']}

    def create_ad_logic(self, account_id, adset_id, media_data, url, head, body, cta, page_id, ad_name_file):
        object_story_spec = {"page_id": page_id}
        if "video_id" in media_data:
            object_story_spec["video_data"] = {
                "video_id": media_data["video_id"], "image_url": media_data["thumbnail_url"],
                "message": body, "title": head, "call_to_action": {"type": cta, "value": {"link": url}}
            }
        else:
            object_story_spec["link_data"] = {
                "image_hash": media_data["image_hash"], "link": url, "message": body, "name": head, "call_to_action": {"type": cta}
            }

        res_cr = requests.post(f"{BASE_URL}/{account_id}/adcreatives", data={
            "name": f"Creative - {ad_name_file}",
            "object_story_spec": json.dumps(object_story_spec), "access_token": self.token
        }).json()
        
        if "id" not in res_cr: raise Exception(f"Error Creativo: {res_cr.get('error', {}).get('message')}")

        res_ad = requests.post(f"{BASE_URL}/{account_id}/ads", data={
            "name": ad_name_file,
            "adset_id": adset_id,
            "creative": json.dumps({"creative_id": res_cr['id']}), "status": "PAUSED", "access_token": self.token
        }).json()
        if "id" not in res_ad: raise Exception(f"Error Anuncio: {res_ad.get('error', {}).get('message')}")
        return True

    # --- FUNCIONES DEL VIGILANTE (Analytics) ---
    def get_insights(self, level, acc_id, date_preset="maximum"):
        fields = ["id", "name", "status", "spend", "impressions", "clicks", "actions", "action_values", "cpc", "ctr", "cpm"]
        params = {
            "access_token": self.token,
            "level": level,
            "date_preset": date_preset,
            "fields": ",".join(fields),
            "limit": 500
        }
        res = requests.get(f"{BASE_URL}/{acc_id}/insights", params=params).json()
        if "error" in res: 
            st.error(f"Error API: {res['error']['message']}")
            return []
        return res.get("data", [])

    def toggle_status(self, node_id, current_status):
        new_status = "PAUSED" if current_status == "ACTIVE" else "ACTIVE"
        url = f"{BASE_URL}/{node_id}"
        params = {"access_token": self.token, "status": new_status}
        requests.post(url, params=params)
        return new_status

# ==============================================================================
# 🖥️ 4. INTERFAZ GRÁFICA (EL CEREBRO DE LA APP)
# ==============================================================================

# --- BARRA LATERAL (LOGIN Y MENÚ) ---
with st.sidebar:
    st.title("⚡ GL Suite")
    
    # MENÚ DE NAVEGACIÓN
    menu = st.radio("📍 Navegación", ["🚀 Lanzador de Ads", "👁️ El Vigilante (Datos)"])
    st.divider()
    
    # LOGIN
    st.subheader("🔑 Credenciales")
    fb_secret = st.secrets.get("FB_ACCESS_TOKEN", "")
    oa_secret = st.secrets.get("OPENAI_API_KEY", "")
    
    fb_token = st.text_input("FB Access Token", value=fb_secret, type="password")
    oa_token = st.text_input("OpenAI API Key", value=oa_secret, type="password")
    
    ad_account_id = None
    manager = None
    acc_name = None
    
    if fb_token:
        try:
            manager = FBAdsManager(fb_token)
            accounts = manager.get_my_ad_accounts()
            if accounts:
                acc_name = st.selectbox("Cuenta Principal (Para Vigilante)", list(accounts.keys()))
                ad_account_id = accounts[acc_name]
        except:
            st.error("Token FB Inválido")

# ==============================================================================
# 🚀 MÓDULO 1: EL LANZADOR
# ==============================================================================
if menu == "🚀 Lanzador de Ads":
    st.title("🚀 Lanzador Multi-Cuenta")
    
    if not manager:
        st.warning("👈 Conecta tu cuenta de Facebook en la barra lateral.")
        st.stop()

    c1, c2 = st.columns([1, 1.2])

    with c1:
        st.subheader("1. Configuración")
        # Aquí permitimos seleccionar VARIAS cuentas para lanzar
        acc_names_sel = st.multiselect("🎯 Cuentas Destino", list(accounts.keys()), default=[acc_name])
        marcas_sel = st.multiselect("Marcas/Países", list(STORE_CONFIG.keys()))
        
        col_d1, col_d2 = st.columns(2)
        fecha_inicio = col_d1.date_input("Fecha Inicio", value=datetime.now() + timedelta(days=1))
        genero_sel = col_d2.selectbox("Género", ["Todos", "Hombres", "Mujeres"])
        
        producto = st.text_input("Producto", "PRODUCTO").upper()
        url_producto = st.text_input("🔗 URL Destino")
        
        st.divider()
        tipo_puja = st.radio("Estrategia", ["ABO (Clásico)", "CBO (Escalado)", "TESTEO_CREATIVOS"])
        
        if tipo_puja == "TESTEO_CREATIVOS":
            presupuesto = st.number_input("Presupuesto por CADA Creativo", value=30000)
        else:
            presupuesto = st.number_input("Presupuesto Total", value=40000)

    with c2:
        st.subheader("2. Creativos")
        tab_local, tab_nube = st.tabs(["📂 Archivos Locales", "☁️ Enlaces Directos"])
        files_to_process = []
        
        with tab_local:
            archivos_local = st.file_uploader("Arrastra aquí", type=['jpg', 'png', 'mp4'], accept_multiple_files=True)
            if archivos_local:
                for f in archivos_local:
                    clean_name = f.name.rsplit('.', 1)[0]
                    final_name = f"{clean_name} - {producto}"
                    files_to_process.append({"type": "file", "obj": f, "mime": f.type, "name": final_name})
        
        with tab_nube:
            urls_text = st.text_area("URLs (uno por línea)", height=100)
            if urls_text:
                for i, url in enumerate(urls_text.split('\n')):
                    if url.strip():
                        mime = "video/mp4" if ".mp4" in url else "image/jpeg"
                        final_name = f"Enlace {i+1} - {producto}"
                        files_to_process.append({"type": "url", "url": url.strip(), "mime": mime, "name": final_name})

        # IA Copy
        if st.button("✨ Generar Copy IA"):
            if not oa_token: st.error("Falta API Key OpenAI.")
            else:
                with st.spinner("Redactando..."):
                    ai = generar_copy_ia(oa_token, producto, "Descripción genérica")
                    st.session_state['ai_h'] = ai.get('headline', '')
                    st.session_state['ai_b'] = ai.get('body', '')

        h_final = st.text_input("Headline", value=st.session_state.get('ai_h', "¡Pide hoy y Paga en Casa!"))
        b_final = st.text_area("Copy", value=st.session_state.get('ai_b', ""), height=150)
        cta = st.selectbox("CTA", ["ORDER_NOW", "SHOP_NOW"])

    st.markdown("---")

    if st.button("🚀 LANZAR CAMPAÑAS", type="primary", use_container_width=True):
        if not marcas_sel or not files_to_process or not url_producto:
            st.error("❌ Faltan datos.")
        else:
            status_main = st.empty()
            url_final = f"https://{url_producto}" if not url_producto.startswith("http") else url_producto
            start_time_unix = int(datetime.combine(fecha_inicio, dt_time(5, 0, 0)).timestamp())
            
            target_genders = []
            if genero_sel == "Hombres": target_genders = [1]
            elif genero_sel == "Mujeres": target_genders = [2]

            for acc_n in acc_names_sel:
                curr_acc_id = accounts[acc_n]
                st.markdown(f"### 📡 Cuenta: {acc_n}")
                
                try:
                    for marca in marcas_sel:
                        cfg = STORE_CONFIG[marca]
                        pais = cfg['country']
                        
                        # 1. Campaña
                        c_name = f"{pais} - {producto} - {tipo_puja[:4]} - {datetime.now().strftime('%d/%m')}"
                        p_camp = {'name': c_name, 'objective': 'OUTCOME_SALES', 'status': 'PAUSED', 'special_ad_categories': '[]', 'access_token': fb_token}
                        if "CBO" in tipo_puja:
                            p_camp['daily_budget'] = int(presupuesto)
                            p_camp['bid_strategy'] = 'LOWEST_COST_WITHOUT_CAP'
                        
                        res_c = requests.post(f"{BASE_URL}/{curr_acc_id}/campaigns", data=p_camp).json()
                        if "id" not in res_c: raise Exception(res_c)
                        camp_id = res_c['id']

                        # Configs AdSet
                        attr = json.dumps([{"event_type": "CLICK_THROUGH", "window_days": 7}, {"event_type": "VIEW_THROUGH", "window_days": 1}])
                        tgt = {'geo_locations': {'countries': [cfg['country_code']]}, 'age_min': 18, 'age_max': 65}
                        if target_genders: tgt['genders'] = target_genders
                        
                        # Estrategia TESTEO
                        if tipo_puja == "TESTEO_CREATIVOS":
                            for idx, item in enumerate(files_to_process):
                                st.write(f"➡️ Subiendo '{item['name']}' a {pais}...")
                                media = manager.upload_media(curr_acc_id, file_obj=item.get("obj"), file_url=item.get("url"), file_type=item["mime"])
                                
                                p_as = {
                                    'name': f"{pais} - TEST {idx+1} ({item['name']})", 'campaign_id': camp_id, 'status': 'PAUSED',
                                    'targeting': json.dumps(tgt), 'start_time': start_time_unix,
                                    'billing_event': 'IMPRESSIONS', 'optimization_goal': 'OFFSITE_CONVERSIONS',
                                    'promoted_object': json.dumps({'pixel_id': cfg['pixelId'], 'custom_event_type': 'PURCHASE'}),
                                    'destination_type': 'WEBSITE', 'attribution_spec': attr,
                                    'bid_strategy': 'LOWEST_COST_WITHOUT_CAP', 'daily_budget': int(presupuesto), 'access_token': fb_token
                                }
                                res_as = requests.post(f"{BASE_URL}/{curr_acc_id}/adsets", data=p_as).json()
                                manager.create_ad_logic(curr_acc_id, res_as['id'], media, url_final, h_final, b_final, cta, cfg['pageId'], item['name'])
                                time.sleep(1)
                        
                        # Estrategia NORMAL
                        else:
                            st.write(f"➡️ Creando Conjunto en {pais}...")
                            p_as = {
                                'name': f"{pais} - OPEN", 'campaign_id': camp_id, 'status': 'PAUSED',
                                'targeting': json.dumps(tgt), 'start_time': start_time_unix,
                                'billing_event': 'IMPRESSIONS', 'optimization_goal': 'OFFSITE_CONVERSIONS',
                                'promoted_object': json.dumps({'pixel_id': cfg['pixelId'], 'custom_event_type': 'PURCHASE'}),
                                'destination_type': 'WEBSITE', 'attribution_spec': attr, 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP', 'access_token': fb_token
                            }
                            if "ABO" in tipo_puja: p_as['daily_budget'] = int(presupuesto)
                            res_as = requests.post(f"{BASE_URL}/{curr_acc_id}/adsets", data=p_as).json()
                            
                            for item in files_to_process:
                                media = manager.upload_media(curr_acc_id, file_obj=item.get("obj"), file_url=item.get("url"), file_type=item["mime"])
                                manager.create_ad_logic(curr_acc_id, res_as['id'], media, url_final, h_final, b_final, cta, cfg['pageId'], item['name'])
                                time.sleep(1)
                        
                        st.success(f"✅ {pais} Listo.")
                except Exception as e:
                    st.error(f"Error: {e}")
            st.balloons()

# ==============================================================================
# 👁️ MÓDULO 2: EL VIGILANTE (ANALYTICS)
# ==============================================================================
elif menu == "👁️ El Vigilante (Datos)":
    st.title(f"👁️ El Vigilante: {acc_name}")
    
    if not manager:
        st.warning("Conecta tu cuenta primero.")
        st.stop()
        
    col_f1, col_f2 = st.columns(2)
    rango_fecha = col_f1.selectbox("📅 Fecha", ["today", "yesterday", "last_3d", "last_7d", "maximum"], index=1)
    nivel = col_f2.selectbox("🔍 Ver por", ["campaign", "adset", "ad"], index=0)
    
    if st.button("🔄 Analizar Datos"):
        with st.spinner("Trayendo datos de Facebook..."):
            data = manager.get_insights(nivel, ad_account_id, date_preset=rango_fecha)
            
            if not data:
                st.warning("No hay datos para mostrar.")
            else:
                rows = []
                for item in data:
                    purchases = 0
                    purchases_val = 0.0
                    
                    if "actions" in item:
                        for act in item["actions"]:
                            if act["action_type"] == "purchase": purchases = int(act["value"])
                    if "action_values" in item:
                        for val in item["action_values"]:
                            if val["action_type"] == "purchase": purchases_val = float(val["value"])
                    
                    spend = float(item.get("spend", 0))
                    cpa = spend / purchases if purchases > 0 else 0
                    roas = purchases_val / spend if spend > 0 else 0
                    
                    rows.append({
                        "ID": item["id"],
                        "Estado": item.get("status", "UNKNOWN"),
                        "Nombre": item["name"],
                        "Gasto": spend,
                        "Ventas": purchases,
                        "CPA": cpa,
                        "ROAS": roas,
                        "CTR": float(item.get("ctr", 0))
                    })
                
                df = pd.DataFrame(rows)
                
                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Gasto Total", f"${df['Gasto'].sum():,.0f}")
                k2.metric("Ventas Totales", f"{df['Ventas'].sum()}")
                k3.metric("CPA Promedio", f"${df['CPA'].mean():,.0f}")
                k4.metric("ROAS Promedio", f"{df['ROAS'].mean():.2f}")
                
                def color_cpa(val):
                    if val == 0: return 'color: black'
                    if val > 40000: return 'color: red' 
                    if val < 20000: return 'color: green'
                    return 'color: orange'
                
                st.subheader("📊 Tabla de Rendimiento")
                st.dataframe(
                    df.style.applymap(color_cpa, subset=['CPA'])
                    .format({"Gasto": "${:,.0f}", "CPA": "${:,.0f}", "ROAS": "{:.2f}", "CTR": "{:.2f}%"}),
                    use_container_width=True
                )
                
                st.divider()
                st.subheader("👮‍♂️ Centro de Control")
                col_c1, col_c2 = st.columns([3, 1])
                target_name = col_c1.selectbox("Selecciona para Cambiar Estado", df['Nombre'].tolist())
                
                if col_c2.button("🚨 Apagar / Prender"):
                    target_row = df[df['Nombre'] == target_name].iloc[0]
                    new_st = manager.toggle_status(target_row['ID'], target_row['Estado'])
                    st.success(f"Cambiado a: {new_st}")
                    time.sleep(1)
                    st.experimental_rerun()
