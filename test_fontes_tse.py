import unittest

from baixar_dados import url_resultados
from baixar_logs import url_logs


class FontesTSETest(unittest.TestCase):
    def test_resultados_2022(self):
        self.assertEqual(
            url_resultados(2022),
            "https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_secao/"
            "detalhe_votacao_secao_2022.zip",
        )

    def test_logs_2022(self):
        self.assertEqual(
            url_logs(2022, 1, "ac"),
            "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/arqurnatot/"
            "bu_imgbu_logjez_rdv_vscmr_2022_1t_AC.zip",
        )
