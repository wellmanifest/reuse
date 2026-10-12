---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "standard-source-reuse",
  "kind": "information",
  "version": 2,
  "title": "Reużytek kanonicznych źródeł standardów",
  "status": "proposed",
  "owner": "wellmanifest/reuse",
  "scope": "repository",
  "created": "2026-10-11",
  "updated": "2026-10-11",
  "review_after": "2026-11-11",
  "source_revision": "4693718f24ae84acfb38d1587779fdb580e2b931",
  "affected_repositories": [
    "wellmanifest/reuse",
    "wellmanifest/ssot",
    "wellmanifest/lifecycle",
    "wellmanifest/new-project",
    "wellmanifest/session-recovery",
    "wellmanifest/metafile",
    "wellmanifest/wellm"
  ],
  "evidence": [
    "repo://wellmanifest/reuse/standard/standard-sources.ssot.json",
    "repo://wellmanifest/reuse/standard/ssot.lock.json",
    "repo://wellmanifest/ssot@4c2df178ad4225ac55c35992a6f2cb859966ee91/schemas/ssot-decision.schema.json"
  ]
}
---

# Reużytek kanonicznych źródeł standardów

<!-- docs:section purpose -->
## Cel

Jedno źródło reguły REUSE-003 i wspólna mapa źródeł pozwalają odróżnić duplikat od dystrybucyjnej kopii standardu. Klasyfikacja reużywa kontrakt SSOT; nie powstaje równoległy język ani parser.

<!-- docs:section scope -->
## Zakres

Profil obejmuje 17 przypiętych źródeł i 24 kopie parsera lifecycle, recovery oraz schematów wellm i metafile. Nie zastępuje profili domenowych ani istniejących updaterów.

<!-- docs:section evidence -->
## Dowody

[Katalog](../../standard/standard-sources.ssot.json) używa `wellmanifest.ssot/decision/v1`. [Lock](../../standard/ssot.lock.json) wiąże dokładną rewizję i SHA-256 schematu oraz kanonicznego walidatora semantycznego SSOT. [Testy](../../tests/test_standard_sources.py) sprawdzają drift, pin, semantykę, integralność kodu walidatora, symlinki, ścieżki i nieśledzone kopie.

<!-- docs:section content -->
## Reguły współdzielenia

- Najpierw wybierz istniejący HOME; nowy standard powstaje tylko dla brakującej wspólnej semantyki.
- `generated_mirror` oraz `vendored_copy` mają jedno źródło przypięte pełnym Git SHA. Zmiany wykonuje właściciel; konsument przyjmuje je przez swój updater.
- Parser należy do lifecycle. Git, tickety, produkty, SaaS, prawo i twin zachowują własne profile oraz bramki.
- Schematy zasobów wellm i metafile są projekcjami pakietów; recovery jest projekcją właściciela session-recovery.
- Podobna nazwa VALIDATE nie jest dowodem identycznej operacji. Aliasy jednego checkoutu nie są dwoma repozytoriami.

Uruchom [checker](../../scripts/check_standard_sources.py) z jawnym `--workspace` i `--ssot-root`. Odczytuje przypięte obiekty Git oraz śledzone pliki konsumentów. Najpierw sprawdza schemat oraz semantykę przez przypięty walidator właściciela SSOT. Kopie zasobów są klasyfikowane jako `vendored_copy` z jawną bramką parity, a nie jako podwójne checkouty. Kod 0 oznacza zgodność kontraktu i wskazanych kopii; 1 oznacza drift; 2 oznacza brak lub niepoprawny kontrakt.

<!-- docs:section limitations -->
## Ograniczenia

Wynik dotyczy wyłącznie konkretnych ścieżek w katalogu. Nie zwalnia całego katalogu .governance z kontroli i nie dowodzi adopcji runtime, podpisu producenta, wykonania testów domenowych ani merge. Pin katalogu i instalacji checkera pozostaje odpowiedzialnością konsumenta.

<!-- docs:section next_actions -->
## Dalsze działania

Zmiany źródła wymagają aktualizacji przypięcia i ponownego odczytu każdej kopii. Niezgodności trafiają do ticketu właściciela; publikacja wymaga niezależnego Validatora. Rollback: cofnąć ten profil i używać dotychczasowych bramek domenowych.
