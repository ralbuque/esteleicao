# Fontes dos arquivos de referência

- `municipios.csv`
  - código do TSE ↔ código do IBGE: [betafcc/Municipios-Brasileiros-TSE](https://github.com/betafcc/Municipios-Brasileiros-TSE)
  - nome e coordenadas do centro de cada município: [kelvins/municipios-brasileiros](https://github.com/kelvins/municipios-brasileiros) (MIT)
  - Boa Esperança do Norte (MT), criado em 2023, não tem código do TSE na tabela; `gerar_site.py` casa pelo nome e UF.
- `../web/mapa/brasil.topo.json`: malha municipal do IBGE via [tbrugz/geodata-br](https://github.com/tbrugz/geodata-br) (CC0),
  simplificada com mapshaper (5% dos vértices, `keep-shapes`) e convertida para TopoJSON com os objetos `municipios`
  (id = código IBGE) e `estados` (id = código IBGE da UF). Sete municípios criados depois da malha aparecem como ponto.

Para refazer o mapa:

```bash
npx mapshaper -i geojs-100-mun.json name=municipios \
  -each 'cod=id; uf=id.slice(0,2); delete name; delete description; delete id' \
  -simplify 5% keep-shapes -dissolve uf + name=estados \
  -o format=topojson target=municipios,estados id-field=cod,uf quantization=40000 brasil.topo.json
```
