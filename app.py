import streamlit as st
import requests
import json
import time
import pandas as pd
from datetime import datetime, timedelta, date

# ==============================================================================
# ⚙️ CONFIGURACIÓN DE PÁGINA
# ==============================================================================
st.set_page_config(
    page_title="GL Ads Suite", 
    layout="wide", 
    page_icon="⚡"
)

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
# 🤖 2. AGENTE DE IA
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
# 🛠️ 3. CLASE DE GESTIÓN FACEBOOK
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

    # --- VIGILANTE MEJORADO ---
    def get_insights_custom(self, level, acc_id, time_params):
        """
        Trae insights con soporte para Campaign Name y Fechas personalizadas.
        time_params: puede ser {'date_preset': 'today'} O {'time_range': {'since': '...', 'until': '...'}}
        """
        endpoint = f"{level}s"
        
        # Pedimos campaign_name explícitamente para mostrarlo en la tabla
        fields = "id,name,campaign_name,status,insights"
        
        # Campos de insights anidados
        insights_fields = "spend,impressions,clicks,actions,action_values,cpc,ctr,cpm"
        
        # Construcción de la consulta anidada
        # Ejemplo: insights.date_preset(today){spend,actions...}
        
        time_key = list(time_params.keys())[0] # date_preset o time_range
        time_val = list(time_params.values())[0]
        
        if time_key == 'time_range':
            # Formato especial para JSON en URL
            time_str = json.dumps(time_val)
            query_insights = f"insights.time_range({time_str}){{{insights_fields}}}"
        else:
            query_insights = f"insights.date_preset({time_val}){{{insights_fields}}}"

        final_fields = f"{fields},{query_insights}"
        
        params = {
            "access_token": self.token,
            "fields": final_fields,
            "limit": 500
        }
        
        res = requests.get(f"{BASE_URL}/{acc_id}/{endpoint}", params=params).json()
        
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
# 🖥️ 4. INTERFAZ GRÁFICA
# ==============================================================================

with st.sidebar:
    st.title("⚡ GL Suite")
    menu = st.radio("📍 Navegación", ["🚀 Lanzador de Ads", "👁️ El Vigilante (Datos)"])
    st.divider()
    
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
            # Este acc_name lo usamos para el Vigilante. El lanzador tiene su propio selector multi-cuenta.
            if accounts:
                acc_name = st.selectbox("Cuenta Principal (Vigilante)", list(accounts.keys()))
                ad_account_id = accounts[acc_name]
        except:
            st.error("Token FB Inválido")

# --- MÓDULO LANZADOR ---
if menu == "🚀 Lanzador de Ads":
    st.title("🚀 Lanzador Multi-Cuenta")
    
    if not manager:
        st.warning("👈 Conecta tu cuenta.")
        st.stop()

    c1, c2 = st.columns([1, 1.2])

    with c1:
        st.subheader("1. Configuración")
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
            url_final = f"https://{url_producto}" if not url_producto.startswith("http") else url_final
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
                        
                        c_name = f"{pais} - {producto} - {tipo_puja[:4]} - {datetime.now().strftime('%d/%m')}"
                        p_camp = {'name': c_name, 'objective': 'OUTCOME_SALES', 'status': 'PAUSED', 'special_ad_categories': '[]', 'access_token': fb_token}
                        if "CBO" in tipo_puja:
                            p_camp['daily_budget'] = int(presupuesto)
                            p_camp['bid_strategy'] = 'LOWEST_COST_WITHOUT_CAP'
                        
                        res_c = requests.post(f"{BASE_URL}/{curr_acc_id}/campaigns", data=p_camp).json()
                        if "id" not in res_c: raise Exception(res_c)
                        camp_id = res_c['id']

                        attr = json.dumps([{"event_type": "CLICK_THROUGH", "window_days": 7}, {"event_type": "VIEW_THROUGH", "window_days": 1}])
                        tgt = {'geo_locations': {'countries': [cfg['country_code']]}, 'age_min': 18, 'age_max': 65}
                        if target_genders: tgt['genders'] = target_genders
                        
                        if tipo_puja == "TESTEO_CREATIVOS":
                            for idx, item in enumerate(files_to_process):
                                st.write(f"➡️ Subiendo '{item['name']}' a {pais}...")
                                media = manager.upload_media(curr_acc_id, file_obj=item.get("obj"), file_url=item.get("url"), file_type=item["mime"])
                                p_as = {'name': f"{pais} - TEST {idx+1} ({item['name']})", 'campaign_id': camp_id, 'status': 'PAUSED', 'targeting': json.dumps(tgt), 'start_time': start_time_unix, 'billing_event': 'IMPRESSIONS', 'optimization_goal': 'OFFSITE_CONVERSIONS', 'promoted_object': json.dumps({'pixel_id': cfg['pixelId'], 'custom_event_type': 'PURCHASE'}), 'destination_type': 'WEBSITE', 'attribution_spec': attr, 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP', 'daily_budget': int(presupuesto), 'access_token': fb_token}
                                res_as = requests.post(f"{BASE_URL}/{curr_acc_id}/adsets", data=p_as).json()
                                manager.create_ad_logic(curr_acc_id, res_as['id'], media, url_final, h_final, b_final, cta, cfg['pageId'], item['name'])
                                time.sleep(1)
                        else:
                            st.write(f"➡️ Creando Conjunto en {pais}...")
                            p_as = {'name': f"{pais} - OPEN", 'campaign_id': camp_id, 'status': 'PAUSED', 'targeting': json.dumps(tgt), 'start_time': start_time_unix, 'billing_event': 'IMPRESSIONS', 'optimization_goal': 'OFFSITE_CONVERSIONS', 'promoted_object': json.dumps({'pixel_id': cfg['pixelId'], 'custom_event_type': 'PURCHASE'}), 'destination_type': 'WEBSITE', 'attribution_spec': attr, 'bid_strategy': 'LOWEST_COST_WITHOUT_CAP', 'access_token': fb_token}
                            if "ABO" in tipo_puja: p_as['daily_budget'] = int(presupuesto)
                            res_as = requests.post(f"{BASE_URL}/{curr_acc_id}/adsets", data=p_as).json()
                            for item in files_to_process:
                                media = manager.upload_media(curr_acc_id, file_obj=item.get("obj"), file_url=item.get("url"), file_type=item["mime"])
                                manager.create_ad_logic(curr_acc_id, res_as['id'], media, url_final, h_final, b_final, cta, cfg['pageId'], item['name'])
                                time.sleep(1)
                        st.success(f"✅ {pais} Listo.")
                except Exception as e: st.error(f"Error: {e}")
            st.balloons()

# --- MÓDULO VIGILANTE ---
elif menu == "👁️ El Vigilante (Datos)":
    st.title(f"👁️ El Vigilante: {acc_name}")
    
    if not manager:
        st.warning("Conecta tu cuenta primero.")
        st.stop()
        
    # --- FILTROS MEJORADOS ---
    col_f1, col_f2 = st.columns([2, 1])
    
    with col_f1:
        # Selector Híbrido: Atajos + Personalizado
        tipo_fecha = st.selectbox("📅 Rango de Fechas", 
                                  ["Hoy", "Ayer", "Últimos 3 días", "Últimos 7 días", "Personalizado"], 
                                  index=0)
        
        # Lógica de fechas
        time_params = {}
        if tipo_fecha == "Hoy": time_params = {'date_preset': 'today'}
        elif tipo_fecha == "Ayer": time_params = {'date_preset': 'yesterday'}
        elif tipo_fecha == "Últimos 3 días": time_params = {'date_preset': 'last_3d'}
        elif tipo_fecha == "Últimos 7 días": time_params = {'date_preset': 'last_7d'}
        elif tipo_fecha == "Personalizado":
            cols_d = st.columns(2)
            d_start = cols_d[0].date_input("Desde", date.today() - timedelta(days=7))
            d_end = cols_d[1].date_input("Hasta", date.today())
            time_params = {'time_range': {'since': str(d_start), 'until': str(d_end)}}

    with col_f2:
        nivel = st.selectbox("🔍 Analizar por", ["campaign", "adset", "ad"], index=0)
    
    st.divider()

    if st.button("🔄 Analizar Datos", type="primary"):
        with st.spinner("Analizando métricas financieras..."):
            
            # Llamamos a la nueva función custom que soporta time_range
            raw_data = manager.get_insights_custom(nivel, ad_account_id, time_params)
            
            if not raw_data:
                st.warning("No se encontraron datos para este periodo.")
            else:
                rows = []
                for item in raw_data:
                    # Datos del objeto
                    obj_id = item.get("id")
                    obj_name = item.get("name")
                    obj_status = item.get("status")
                    camp_name = item.get("campaign_name", "N/A") # Nombre de la campaña
                    if nivel == "campaign": camp_name = obj_name # Si vemos campañas, el nombre es el mismo

                    # Insights (si existen, a veces items pausados no traen insights)
                    insights_data = {}
                    if "insights" in item and "data" in item["insights"]:
                        insights_data = item["insights"]["data"][0]

                    spend = float(insights_data.get("spend", 0))
                    impressions = int(insights_data.get("impressions", 0))
                    
                    # --- CÁLCULO DE COMPRAS Y FACTURADO ---
                    purchases = 0
                    facturado = 0.0 # Revenue
                    
                    if "actions" in insights_data:
                        for act in insights_data["actions"]:
                            if act["action_type"] == "purchase": 
                                purchases = int(act["value"])
                    
                    if "action_values" in insights_data:
                        for val in insights_data["action_values"]:
                            if val["action_type"] == "purchase": 
                                facturado = float(val["value"])
                    
                    # --- KPIs ---
                    # Costo por Compra = Gasto / Compras
                    costo_por_compra = spend / purchases if purchases > 0 else 0
                    
                    # ROAS = Facturado / Gasto
                    roas = facturado / spend if spend > 0 else 0
                    
                    rows.append({
                        "ID": obj_id,
                        "Campaña": camp_name, # Nueva columna
                        "Nombre": obj_name,
                        "Estado": obj_status,
                        "Gasto": spend,
                        "Facturado": facturado, # Nueva columna
                        "Costo x Compra": costo_por_compra, # Renombrado
                        "Compras": purchases,
                        "ROAS": roas
                    })
                
                df = pd.DataFrame(rows)
                
                # --- VISUALIZACIÓN DE MÉTRICAS GLOBALES ---
                st.markdown("### 📊 Resumen Financiero")
                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Gasto Total", f"${df['Gasto'].sum():,.0f}")
                k2.metric("Facturado (Total)", f"${df['Facturado'].sum():,.0f}")
                k3.metric("Compras Totales", f"{df['Compras'].sum()}")
                
                # Promedios ponderados
                avg_cpp = df['Gasto'].sum() / df['Compras'].sum() if df['Compras'].sum() > 0 else 0
                avg_roas = df['Facturado'].sum() / df['Gasto'].sum() if df['Gasto'].sum() > 0 else 0
                
                k4.metric("Costo x Compra (Avg)", f"${avg_cpp:,.0f}")
                k5.metric("ROAS Global", f"{avg_roas:.2f}x")
                
                # --- TABLA DETALLADA ---
                def color_cpp(val):
                    if val == 0: return 'color: gray'
                    if val > 40000: return 'color: red; font-weight: bold' 
                    if val < 20000: return 'color: green; font-weight: bold'
                    return 'color: black'
                
                st.subheader("📋 Detalle de Rendimiento")
                
                # Ordenar columnas
                cols_order = ["Estado", "Campaña", "Nombre", "Gasto", "Facturado", "Compras", "Costo x Compra", "ROAS"]
                
                st.dataframe(
                    df[cols_order].style.applymap(color_cpp, subset=['Costo x Compra'])
                    .format({
                        "Gasto": "${:,.0f}", 
                        "Facturado": "${:,.0f}", 
                        "Costo x Compra": "${:,.0f}", 
                        "ROAS": "{:.2f}x"
                    }),
                    use_container_width=True,
                    height=500
                )
                
                # --- CONTROL ---
                st.divider()
                st.subheader("👮‍♂️ Acciones Rápidas")
                col_c1, col_c2 = st.columns([3, 1])
                target_name = col_c1.selectbox("Selecciona elemento para Apagar/Prender:", df['Nombre'].tolist())
                
                if col_c2.button("🚨 Cambiar Estado"):
                    target_row = df[df['Nombre'] == target_name].iloc[0]
                    new_st = manager.toggle_status(target_row['ID'], target_row['Estado'])
                    st.success(f"✅ Estado actualizado a: {new_st}")
                    time.sleep(1)
                    st.experimental_rerun()
