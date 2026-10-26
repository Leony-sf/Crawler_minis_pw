import urllib.request
import os

ANATEL_DATA_URL = "https://dados.gov.br/dados-abertos/dataset/produtos-homologados-anatel/resource/download"
OUTPUT_FILE = "Produtos_Homologados_Anatel.csv"

def atualizar_base():
    print(f"Iniciando download da base oficial da Anatel...")
    try:
        urllib.request.urlretrieve(ANATEL_DATA_URL, OUTPUT_FILE)
        print(f"Base da Anatel atualizada com sucesso: {OUTPUT_FILE}")
    except Exception as e:
        print(f"Erro ao baixar a base da Anatel: {e}")
        print("Certifique-se de que a URL de dados abertos está acessível ou atualizada.")

if __name__ == "__main__":
    atualizar_base()