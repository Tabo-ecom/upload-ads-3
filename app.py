import streamlit as st
import requests
import json
from datetime import date

# ==============================================================================
# ⚙️ CONFIGURACIÓN DE TIENDAS (EDITA TUS DATOS AQUÍ)
# ==============================================================================
# IMPORTANTE: Reemplaza los '00000...' con tus IDs reales.
# Si no los cambias, Facebook dará error porque no sabrá qué página usar.

CONFIG_TIENDAS = {
    "COLOMBIA": {
        "currency": "COP",
        "page_id": "0000000000000",       # <-- BORRA ESTOS CEROS Y PON EL ID DE TU FANPAGE COLOMBIA
        "pixel_id": "0000000000000",      # <-- BORRA ESTOS CEROS Y PON EL ID DE TU PIXEL COLOMBIA
        "geo_location": {"countries": ["CO"]},             
        "timezone": "America/Bogota"
    },
    "ECUADOR": {
        "currency": "USD",
        "page_id": "0000000000000",       # <-- ID FANPAGE ECUADOR
        "pixel_id": "0000000000000",      # <-- ID PIXEL ECUADOR
        "geo_location": {"countries": ["EC"]},
        "timezone": "America/Guayaquil"
    },
    "GUATEMALA": {
        "currency": "GTQ",
        "page_id": "0000000000000",       # <-- ID FANPAGE GUATEMALA
        "pixel_id": "0000000000000",      # <-- ID PIXEL GUATEMALA
        "geo_location": {"countries": ["GT"]},
        "timezone": "America/Guatemala"
    }
}

# --- VERSIÓN API ACTUALIZADA (SOLUCIÓN ERROR #2635) ---
API_VERSION = "v22.0" 
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# ==============================================================================
# 🔌 FUNCIONES DE CONEXIÓN CON FACEBOOK (GRAPH API)
# ==============================================================================

def get_ad_accounts(token):
    """Obtiene tus cuentas publicitarias."""
    try:
        url = f"{BASE_URL}/me/adaccounts"
        params = {"access_token": token, "fields": "name,account_id,currency", "limit": 50}
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json().get('data', [])
            return {f"{acc['name']} ({acc['currency']})" : f"act_{acc['account_id']}" for acc in data}
        return {}
    except:
        return {}

def upload_ad_image(account_id, token, image_file):
    """Sube la imagen y obtiene el HASH necesario para el anuncio."""
    url = f"{BASE_URL}/{account_id}/adimages"
    image_file.seek(0)
    files = {'file': (image_file.name, image_file, image_file.type)}
    params = {'access_token': token}
    
    response = requests.post(url, params=params, files=files)
    data = response.json()
    
    if 'images' in data:
        key = list(data['images'].keys())[0]
        return data['images'][key]['hash']
    else:
        error_msg = data.get('error', {}).get('message', 'Error desconocido')
        raise Exception(f"Error subiendo imagen: {error_msg}")

def create_campaign(account_id, token, name, objective, budget_mode, daily_budget):
    """Crea la campaña en estado PAUSADO."""
    url = f"{BASE_URL}/{account_id}/campaigns"
    payload = {
        'name': name,
        'objective': objective,
        'status': 'PAUSED',
        'special_ad_categories': json.dumps(['NONE']),
        'access_token': token
    }
    
    if budget_mode == "CBO (Advantage+)":
        payload['daily_budget'] = int(daily_budget * 100) # Centavos
        payload['bid_strategy'] = 'LOWEST_COST_WITHOUT_CAP'
    
    response = requests.post(url, data=payload)
    data = response.json()
    
    if 'id' in data:
        return data['id']
    else:
        raise Exception(f"Error creando Campaña: {data.get('error', {}).get('message')}")

def create_adset(account_id, token, campaign_id, name, targeting, pixel_id, objective, daily_budget, budget_mode):
    """Crea el conjunto de anuncios con la segmentación y Pixel."""
    url = f"{BASE_URL}/{account_id}/adsets"
    
    payload = {
        'name': name,
        'campaign_id': campaign_id,
        'status': 'PAUSED',
        'targeting': json.dumps(targeting),
        'billing_event': 'IMPRESSIONS',
        'bid_strategy': 'LOWEST_COST_WITHOUT_CAP',
        'access_token': token
    }

    if budget_mode == "ABO":
        payload['daily_budget'] = int(daily_budget * 100)

    # Configuración de Pixel
    if objective == "OUTCOME_SALES":
        payload['optimization_goal'] = 'OFFSITE_CONVERSIONS'
        payload['destination_type'] = 'WEBSITE'
        payload['promoted_object'] = json.dumps({
            'pixel_id': pixel_id,
            'custom_event_type': 'PURCHASE'
        })
    elif objective == "OUTCOME_TRAFFIC":
        payload['optimization_goal'] = 'LINK_CLICKS'
    
    response = requests.post(url, data=payload)
    data = response.json()
    
    if 'id' in data:
        return data['id']
    else:
        raise Exception(f"Error creando AdSet: {data.get('error', {}).get('message')}")

def create_ad_creative(account_id, token, name, page_id, image_hash, title, body, link, cta):
    """Crea la parte visual del anuncio."""
    url = f"{BASE_URL}/{account_id}/adcreatives"
    
    object_story_spec = {
        'page_id': page_id,
        'link_data': {
            'image_hash': image_hash,
            'link': link,
            'message': body,
            'name': title,
            'call_to_action': {'type': cta}
        }
    }
    
    payload = {
        'name': name,
        'object_story_spec': json.dumps(object_story_spec),
        'access_token': token
    }
    
    response = requests.post(url, data=payload)
    data = response.json()
    
    if 'id' in data:
        return data['id']
    else:
        raise Exception(f"Error creando Creativo: {data.get('error', {}).get('message')}")

def create_ad(account_id, token, adset_id, creative_id, name):
    """Une todo y crea el anuncio final."""
    url = f"{BASE_URL}/{account_id}/ads"
    payload = {
        'name': name,
        'adset_id': adset_id,
        'creative': json.dumps({'creative_id': creative_id}),
        'status': 'PAUSED',
        'access_token': token
    }
    
    response = requests.post(url, data=payload)
    data = response.json()
    
    if 'id' in data:
        return data['id']
    else:
        raise Exception(f"Error creando Anuncio: {data.get('error', {}).get('message')}")

# ==============================================================================
# 🖥️ INTERFAZ DE USUARIO (STREAMLIT)
# ==============================================================================

st.set_page_config(page_title="GL Group Ads Launcher", page_icon="🚀", layout="wide")

st.title("🚀 GL Group Ads Launcher")
st.markdown(f"### Lanza campañas reales en Facebook (API {API_VERSION})")

# --- BARRA LATERAL ---
st.sidebar.header("🔐 Llaves de Acceso")
fb_token = st.sidebar.text_input("Pega tu Token de Facebook", type="password")

selected_account_id = None
if fb_token:
    accounts = get_ad_accounts(fb_token)
    if accounts:
        acc_name = st.sidebar.selectbox("Selecciona la Cuenta Publicitaria", list(accounts.keys()))
        selected_account_id = accounts[acc_name]
    else:
        st.sidebar.error("El token no es válido o no tiene permisos.")

st.sidebar.divider()
st.sidebar.info("Asegúrate de haber puesto tus IDs de Página y Píxel en el código.")

if not selected_account_id:
    st.warning("👈 Ingresa tu Token para empezar.")
    st.stop()

# --- FORMULARIO ---

col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Estrategia Global")
    countries = st.multiselect("¿A qué países lanzar?", list(CONFIG_TIENDAS.keys()), default=["COLOMBIA"])
    product_name = st.text_input("Nombre del Producto", "MASCARILLA")
    
    c1, c2 = st.columns(2)
    budget = c1.number_input("Presupuesto Diario", min_value=1000, value=50000, step=5000)
    budget_type = c2.selectbox("Tipo de Presupuesto", ["CBO (Advantage+)", "ABO"])
    
    objective_map = {"Ventas (Sales)": "OUTCOME_SALES", "Tráfico": "OUTCOME_TRAFFIC"}
    objective_ui = st.radio("Objetivo", list(objective_map.keys()))
    objective_api = objective_map[objective_ui]

with col2:
    st.subheader("2. Diseño del Anuncio")
    uploaded_image = st.file_uploader("Sube la Imagen o Video", type=['jpg', 'png', 'mp4'])
    headline = st.text_input("Título (Headline)", "¡Oferta Limitada!")
    copy = st.text_area("Texto Principal (Copy)", "Escribe aquí los beneficios...", height=120)
    cta = st.selectbox("Botón (CTA)", ["SHOP_NOW", "ORDER_NOW", "LEARN_MORE", "GET_OFFER"])
    dest_link = st.text_input("Link de Destino", "https://glgroup.com/producto")

st.divider()

if st.button("🚀 CREAR CAMPAÑAS", type="primary", use_container_width=True):
    if not uploaded_image or not countries:
        st.error("❌ Faltan datos (Imagen o País).")
    else:
        progress_bar = st.progress(0)
        status_box = st.empty()
        
        try:
            status_box.info("📤 Subiendo imagen a Facebook...")
            image_hash = upload_ad_image(selected_account_id, fb_token, uploaded_image)
            st.toast(f"✅ Imagen subida.")
            
            for i, country in enumerate(countries):
                assets = CONFIG_TIENDAS[country]
                
                # Validar que se hayan cambiado los IDs
                if "00000" in str(assets['page_id']) or "00000" in str(assets['pixel_id']):
                    st.error(f"❌ ERROR EN {country}: No has configurado el Page ID o Pixel ID en el código.")
                    continue

                # Nombres automáticos
                camp_name = f"{country} - {product_name.upper()} - {date.today()} - {objective_ui}"
                adset_name = f"{country} - {product_name} - Open"
                ad_name = f"Ad 1 - {product_name}"
                
                # Proceso de creación
                status_box.info(f"[{country}] 🏗️ Creando Campaña...")
                camp_id = create_campaign(selected_account_id, fb_token, camp_name, objective_api, budget_type, budget)
                
                status_box.info(f"[{country}] 🎯 Segmentando...")
                adset_id = create_adset(selected_account_id, fb_token, camp_id, adset_name, assets['geo_location'], assets['pixel_id'], objective_api, budget, budget_type)
                
                status_box.info(f"[{country}] 🎨 Diseñando Anuncio...")
                creative_id = create_ad_creative(selected_account_id, fb_token, f"Creative - {product_name}", assets['page_id'], image_hash, headline, copy, dest_link, cta)
                
                status_box.info(f"[{country}] 🚀 Finalizando...")
                create_ad(selected_account_id, fb_token, adset_id, creative_id, ad_name)
                
                st.success(f"✅ {country}: Campaña creada (ID: {camp_id})")
                progress_bar.progress((i + 1) / len(countries))
                
            status_box.success("🎉 ¡PROCESO TERMINADO! Revisa tu Business Manager.")
            
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
