# Măsurători mișcare `/` (înainte)

`node scripts/verifica-index-miscare.mjs`, pas 2% din derulare, 2 rulări identice. JSON: `docs/polish/capturi-miscare/masuratori.json`.
Celulă = start / final / ține / vizibil (% derulare). Start = primul pas cu altă stare decât la 0% (la hero = începutul ieșirii). Final = opacity 1, transform none, clip deschis, plus vizibil efectiv (strat/părinte vizibil, în ecran). „—” = nu se schimbă.

| element | 390x844 | 900x900 | 1440x900 |
|---|---|---|---|
| strat0 | 12/0/10/0-10 | 12/0/10/0-10 | 12/0/10/0-10 |
| strat1 | 12/12/18/12-30 | 12/12/16/12-28 | 12/12/16/12-28 |
| strat2 | 30/30/18/30-48 | 30/30/18/30-48 | 30/30/18/30-48 |
| strat3 | 50/50/16/50-66 | 50/50/16/50-66 | 50/50/16/50-66 |
| strat4 | 68/68/16/68-84 | 68/68/16/68-84 | 68/68/16/68-84 |
| strat5 | 86/86/14/86-100 | 86/86/14/86-100 | 86/86/14/86-100 |
| h1 | 6/0/4/0-10 | 6/0/4/0-10 | 6/0/4/0-10 |
| subtitlu | 6/0/4/0-6 | 6/0/4/0-6 | 6/0/4/0-6 |
| vaza | —/0/10/0-10 | —/0/10/0-10 | —/0/10/0-10 |
| inel-prim | —/0/10/0-10 | —/0/10/0-10 | —/0/10/0-10 |
| inel-ultim | 2/0/0/0-10 | 2/0/0/0-10 | 2/0/0/0-10 |
| filament | —/0/100/0-100 | —/0/100/0-100 | —/0/100/0-100 |
| text1 | 14/20/4/12-30 | 14/20/4/12-28 | 14/20/4/12-28 |
| poza1 | 12/12/14/12-28 | 12/12/14/12-28 | 12/12/14/12-28 |
| text2 | 32/38/6/30-48 | 32/38/6/30-48 | 32/38/6/30-48 |
| poza2 | 30/30/14/30-46 | 30/30/14/30-46 | 30/30/14/30-46 |
| text3 | 50/56/6/50-66 | 52/56/6/50-66 | 52/56/6/50-66 |
| poza3 | 50/50/12/50-66 | 50/50/12/50-66 | 50/50/12/50-66 |
| la-comanda | 68/68/16/68-84 | 68/68/16/68-84 | 68/68/16/68-84 |
| contact | 86/86/14/86-100 | 86/86/14/86-100 | 86/86/14/86-100 |
| footer | 90/94/6/90-100 | 90/94/6/90-100 | 90/94/6/90-100 |

Nu ajung la final: —.

- 390x844: două straturi vizibile (opacity efectivă>0,1, în ecran, clip deschis): 30-30; ecran gol: —; overflow orizontal: —; CLS 0
- 900x900: două straturi vizibile (opacity efectivă>0,1, în ecran, clip deschis): —; ecran gol: —; overflow orizontal: —; CLS 0
- 1440x900: două straturi vizibile (opacity efectivă>0,1, în ecran, clip deschis): —; ecran gol: —; overflow orizontal: —; CLS 0.0002

- reduced-motion 390x844: totul vizibil da; overflow —; CLS 0
- reduced-motion 900x900: totul vizibil da; overflow —; CLS 0
- reduced-motion 1440x900: totul vizibil da; overflow —; CLS 0.0002
- fără view() 390x844: totul vizibil da; overflow —; CLS 0
- fără view() 900x900: totul vizibil da; overflow —; CLS 0
- fără view() 1440x900: totul vizibil da; overflow —; CLS 0.0002

Capturi: `docs/polish/capturi-miscare/hero-390-mic.png`, `docs/polish/capturi-miscare/hero-900-mic.png`, `docs/polish/capturi-miscare/hero-1440-mic.png`
