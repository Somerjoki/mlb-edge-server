# MLB Edge Backend

Automaattinen Pinnacle-kertoimien keräys ja tulosten seuranta.

## Railway.app käyttöönotto

1. Mene railway.app ja kirjaudu GitHub-tunnuksilla
2. New Project → Deploy from GitHub repo
3. Valitse tämä repository
4. Railway tunnistaa automaattisesti Python-projektin
5. Lisää environment variable: ei tarvita (API key on koodissa)
6. Deploy käynnistyy automaattisesti

## API Endpoints

- GET /api/games — tulevan päivän pelit kertoimilla
- GET /api/results — menneet pelit tuloksineen  
- GET /api/all — kaikki pelit
- GET /api/status — palvelimen tila
- POST /api/fetch — manuaalinen haku

## Aikataulu

- klo 10:00 FIN — avauskertoimet
- klo 19:00 FIN — sulkeutumiskertoimet (itärannikko)
- klo 02:00 FIN — sulkeutumiskertoimet (länsirannikko)
- 15min välein — tulokset MLB API:sta
