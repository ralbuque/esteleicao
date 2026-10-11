import pandas as pd
import unittest

from comparacao import comparar_secoes, resumo_comparacao


def _base(secoes):
    linhas = []
    for secao, f_abst, f_17, f_man in secoes:
        linhas.append({
            "uf": "SP", "cd_municipio": 1, "zona": 1, "secao": secao,
            "aptos": 100, "comparecimento": 90, "abstencoes": 10,
            "taxa_abstencao": .10, "z_ajustado": -3 if f_abst else 0,
            "n_criterios": int(f_abst) + int(f_17) + int(f_man),
            "criterios_cumpridos": "", "f_abst": f_abst, "f_17": f_17,
            "f_man": f_man, "alerta": "sinalizada" if any((f_abst, f_17, f_man)) else "normal",
            "tem_log": f_17 or f_man,
        })
    return pd.DataFrame(linhas)


class ComparacaoTest(unittest.TestCase):
    def test_compara_persistentes_novas_resolvidas_e_sem_par(self):
        anterior = _base([(1, True, False, False), (2, False, False, False), (3, True, False, False)])
        atual = _base([(1, True, False, False), (2, False, True, False),
                       (3, False, False, False), (4, True, False, False)])

        comparacao = comparar_secoes(anterior, atual, ("2022_t1", "2026_t1"))
        situacoes = comparacao.set_index("secao")["situacao"]

        self.assertEqual(situacoes[1], "persistente")
        self.assertEqual(situacoes[2], "nova em 2026_t1")
        self.assertEqual(situacoes[3], "resolvida em 2026_t1")
        self.assertEqual(comparacao.set_index("secao").loc[4, "pareamento"], "somente 2026_t1")
        self.assertEqual(situacoes[4], "somente 2026_t1")

        resumo = resumo_comparacao(comparacao, ("2022_t1", "2026_t1")).iloc[0]
        self.assertEqual(resumo["pareadas"], 3)
        self.assertEqual(resumo["somente_2026_t1"], 1)
