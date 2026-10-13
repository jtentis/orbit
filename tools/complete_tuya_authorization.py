"""Complete an explicitly authorized Tuya QR session and configure LAN lighting.

Reads ephemeral QR state from Windows DPAPI. Does not print keys, auth tokens or
account identifiers. Only queries candidate IDs discovered on the local LAN.
"""
import sys
import time
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tuya_sharing import LoginControl
from tuya_sharing.customerapi import CustomerApi, CustomerTokenInfo
from tuya_sharing.customerlogging import logger
from shared.storage import load_secret, save_secret, load_config, save_config, DATA_DIR
from lamp.local import LocalLamp, discover_local

CLIENT = 'HA_3y9q4ak7g4ephrvke'
logger.disabled = True # SDK errors may include decrypted credentials.


def bounded(session):
    request = session.request
    def call(method, url, **kwargs):
        parsed = urlparse(url)
        allowed = parsed.hostname and (parsed.hostname.endswith('.iotbing.com') or parsed.hostname in ('apigw.tuyaus.com', 'apigw.tuyaeu.com', 'apigw.tuyacn.com'))
        if parsed.scheme != 'https' or not allowed:
            raise RuntimeError('Endpoint Tuya inesperado.')
        return request(method, url, **{**kwargs, 'timeout': (5, 8), 'allow_redirects': False})
    session.request = call


def main():
    secret = load_secret('tuya-qr-session')
    if not secret: raise RuntimeError('Não há sessão QR pendente.')
    cached = load_secret('tuya-qr-auth')
    if cached and cached.get('user_code') == secret['user_code']:
        auth = cached['auth']
    else:
        login = LoginControl(); bounded(login.session)
        try:
            success, auth = login.login_result(secret['qr_token'], CLIENT, secret['user_code'])
        finally:
            login.session.close()
        if not success:
            print('Autorização ainda não disponível; código de resposta:', auth.get('code', 'desconhecido'))
            return 2
        save_secret('tuya-qr-auth', {'auth': auth, 'user_code': secret['user_code']})
    print('Autorização Tuya confirmada.', flush=True)
    candidates = discover_local()
    if not candidates: raise RuntimeError('Nenhum dispositivo Tuya encontrado na rede.')
    api = CustomerApi(CustomerTokenInfo(auth), CLIENT, secret['user_code'], auth['endpoint'], None)
    bounded(api.session)
    device = LocalLamp()
    try:
        homes = api.get('/v1.0/m/life/users/homes')
        if not homes or not homes.get('success') or not isinstance(homes.get('result'), list):
            raise RuntimeError('A conta não retornou as casas autorizadas.')
        if len(homes['result']) > 20: raise RuntimeError('Número de casas acima do limite da configuração local.')
        candidate_ids = {item['device_id'] for item in candidates}
        lighting_by_id = {}
        for home in homes['result']:
            result = api.get('/v1.0/m/life/ha/home/devices', {'homeId': str(home['ownerId'])})
            if not result or not result.get('success') or not isinstance(result.get('result'), list):
                raise RuntimeError('A conta não retornou os dispositivos autorizados.')
            for item in result['result']:
                if item.get('id') in candidate_ids and item.get('category') in ('dj', 'dd', 'fwd', 'xdd', 'dc'):
                    lighting_by_id[item['id']] = item
        lighting = list(lighting_by_id.values())
        if len(lighting) != 1:
            print('Lâmpadas da conta correspondentes à rede:', len(lighting))
            return 3
        cloud = lighting[0]
        info = next((item for item in candidates if item['device_id'] == cloud.get('id')), None)
        if not info: raise RuntimeError('A identidade da lâmpada não corresponde à descoberta local.')
        key = cloud.get('local_key') or cloud.get('localKey')
        if not isinstance(key, str) or len(key.encode('utf-8')) != 16:
            raise RuntimeError('A conta não forneceu uma chave local válida para a lâmpada.')
        state = device.connect(info, key)
        name = cloud.get('name') or cloud.get('product_name') or 'Smarteck SLAMP1'
        configured = {**info, 'name': name}
        save_secret('local-lamp', {'key': key, 'device_id': info['device_id']})
        config = load_config(); config['lamp'] = configured; save_config(config)
        print('Lâmpada configurada:', name)
        print('IP local:', info['host'], 'protocolo:', info['version'])
        print('Leitura real:', {'power': state.power, 'level': state.level, 'white_percentage': state.kelvin,
                              'mode': state.color_mode, 'hue': round(state.hue or 0, 2), 'saturation': round(state.saturation or 0, 2)})
        print('Chave recebida e protegida pelo Windows; nenhum comando de iluminação enviado.')
        for name in ('tuya-qr-session', 'tuya-qr-auth'):
            (DATA_DIR / (name+'.dpapi')).unlink(missing_ok=True)
        return 0
    finally:
        device.close(); api.session.close()


if __name__ == '__main__':
    try:
        result = main()
    except Exception as error:
        print('Falha segura ao concluir conexão:', type(error).__name__)
        result = 1
    sys.exit(result)
