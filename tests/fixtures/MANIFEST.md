# Fixture Manifest

Every file here is an **unmodified** download from a public NSE archive URL. Never edit a
fixture in place; add a new file and a new row instead. `tests/test_fixture_integrity.py`
fails if any SHA-256 below stops matching.

Fetched 2026-11-13 from a cloud container (`nsearchives.nseindia.com` answered HTTP 200;
`www.nseindia.com` and `api.bseindia.com` answered HTTP 403).

## XBRL (quarterly results, Integrated Filing / legacy)

| File | Issuer (from file) | Profile | Period | SHA-256 |
|---|---|---|---|---|
| `xbrl/INTEGRATED_FILING_INDAS_1753867_05112026061857_WEB.xml` | ELIN Electronics Ltd (ELIN, INE050401020), Standalone | INDAS_CORP | Q2 FY27 (Jul–Sep 2026) | `87addff94b4390324ed85abfcf77abb13feb75ef2ba53c7cf808046668186f6c` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1757118_13112026023256_WEB.xml` | Jindal Poly Investment & Finance Co (JPOLYINVST, INE147P01019), Standalone | INDAS_NBFC | Q2 FY27 | `1201599e51fc77cc9e36d6b4d981df57ccdfa6b90dfd1a7a54ee01bb2d8b22ed` |
| `xbrl/INTEGRATED_FILING_BANKING_1699494_22072026061940_WEB.xml` | CSB Bank Ltd (CSBBANK, INE679A01013), Standalone | IGAAP_BANK | Q1 FY27 (Apr–Jun 2026) | `00f1f6a3a21c28b278dbc5a2649c23771ccc25d04e2ad3e82408ae3410f3bc87` |
| `xbrl/GI_117901_1363602_28012025065616.xml` | Star Health & Allied Insurance (STARHEALTH, INE575P01011), Standalone | IRDAI_GENERAL_INSURANCE (legacy BSE taxonomy) | Q3 FY25 (Oct–Dec 2024) | `930307c06c8376ad686b193c138071c761825de56034fc57d7088dd1e4348f7b` |
| `xbrl/SHP_1739151_15102026054406_WEB.xml` | ELIN Electronics Ltd, Reg. 31 shareholding as of 2026-09-30 | REG31_SHP (`in-bse-shp` 2025-10-31) | 2026-09-30 | `b11684009c52a2978dc24ac5214981c2ebc5b13cca1f2915b86f27ebe4c733a6` |

URL pattern: `https://nsearchives.nseindia.com/corporate/xbrl/<file name>`.

Coverage note: the JPOLYINVST NBFC fixture is an investment holding company; the lending NBFC,
life insurer, H1 bank, consolidated corporate, Reg. 34 annual and pledged Reg. 31 fixtures are in the
"Phase 2 evidence XBRL" section below.

## Bhavcopy

| File | Why it is here | SHA-256 |
|---|---|---|
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250919_F_0000.csv.zip` | Day before ADANIPOWER 1:5 split ex-date | `082cdbde89ba1bf28633be126645b353c10b0e0e31190e7b43193917b9858d89` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250922_F_0000.csv.zip` | ADANIPOWER split ex-date (ISIN change) | `317ca34ae71af34a77848368be9b6c54a3e54c8e52763f63c3fa43cd17f3f2f6` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250923_F_0000.csv.zip` | PIDILITIND 1:1 bonus ex-date (ISIN unchanged) | `9c25bc8800a0d9c565a9ecbe69e04e2d3959c6ee08221e7d4e0e3425e95deb58` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251013_F_0000.csv.zip` | Day before TATAMOTORS demerger ex-date | `b2041ef799e831432238f2add4249502abc69cb60a76f3c686f5bbef2aeabe58` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251014_F_0000.csv.zip` | TATAMOTORS demerger ex-date; TATAINVEST split | `5bd4f7e4243e8744fc1dfdf7c774eb0b1109c2e6c16e743cd335492973410ed9` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20261112_F_0000.csv.zip` | 2026-11-12: prices near ELIN's Q2 FY27 results/Reg. 31 filings; TATAMOTORS now trades as TMPV (same ISIN) | `b28a71c49f757ceff661093fd308ef6e49740ea583c9fb214f836a3b011e0652` |
| `bhavcopy/sec_bhavdata_full_12112026.csv` | Delivery file for 2026-11-12 | `353e958e149f082b915b7f1844a7ba7cf0e535db0d6329c3e0c24d2928974b04` |
| `bhavcopy/sec_bhavdata_full_14102025.csv` | Delivery file for 2025-10-14 (`PREV_CLOSE`, `DELIV_QTY`) | `d72fcbad87c23165dd64a0c7f21f72392d96a7b1b2a58a3dca2c681850d8ab03` |

URL patterns:
- `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_<YYYYMMDD>_F_0000.csv.zip`
- `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv`

## Corporate actions, shareholding index, calendar, constituents (fetched 2026-11-13)

`www.nseindia.com/api/...` endpoints below answered HTTP 200 from the cloud container with a
plain browser User-Agent and no cookie warm-up (the `www.nseindia.com/` HTML page itself returned 403).

| File | Source URL | SHA-256 |
|---|---|---|
| `corp_actions/nse_corporateActions_equities_15-09-2025_17-10-2025.json` | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=15-09-2025&to_date=17-10-2025` | `b824525e17fc0135744e8601853656270ccd7d2fbf6fd08fda10db361766ae45` |
| `corp_actions/RSS_Corporate_action_20261113.xml` | `https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml` | `707c513ee6ccc3133177764905268ff2ea153b7928064c1e21b8edc8e055000b` |
| `shareholding/nse_corporate-share-holdings-master_ELIN_20261113.json` | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=ELIN` | `a2e98bfe83e1ae51f03a505e7ee305d7f38431d1b580d16cd1f830d21a516a1c` |
| `indices/ind_nifty500list_20261113.csv` | `https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv` | `31b764a95cc03ad1d7ddb6c42340de9125ed2c78b3d436bf0dbc8440e4e38c5e` |
| `calendar/nse_holiday-master_trading_20261113.json` | `https://www.nseindia.com/api/holiday-master?type=trading` | `8903f442b9b3bef9bb1e835112ffae68faab995948d591adc9dcbd6ddd056d6a` |

## NSE Indices change notices (fetched 2026-11-13 from niftyindices.com)

The 12 notices with a `Nifty 500` replacement table effective after 2024-10-01, plus one prose-only
demerger notice (`ind_prs13112025`, DUMMYTATAM). The `.txt` files are **derived** (exact `pdftotext -layout`
output); `tests/test_index_backfill.py::test_derived_text_matches_pdf` regenerates and compares them.

| File | Source | SHA-256 |
|---|---|---|
| `index_changes/pdf/ind_prs04042025_2.pdf` | `https://niftyindices.com/Press_Release/ind_prs04042025_2.pdf` | `05071b75b7edb04262a0503129397e4b231cfcf3ba118399057f7a76c949398d` |
| `index_changes/pdf/ind_prs04052026.pdf` | `https://niftyindices.com/Press_Release/ind_prs04052026.pdf` | `686327d0d4c7d096cab36bdd2e548fdc4d5f0b18b402cc3f3038cfc62c2d23b6` |
| `index_changes/pdf/ind_prs04102024.pdf` | `https://niftyindices.com/Press_Release/ind_prs04102024.pdf` | `ef6e793102e20cb51d56a054e5413e0df6b995004b14fea7425e659c403650cf` |
| `index_changes/pdf/ind_prs10082026.pdf` | `https://niftyindices.com/Press_Release/ind_prs10082026.pdf` | `56a3d162e4aabd8767686010afb01eb8dd21dc089d5cf8995a8a34091eef9bff` |
| `index_changes/pdf/ind_prs10102024.pdf` | `https://niftyindices.com/Press_Release/ind_prs10102024.pdf` | `415d454c98245950494cf51f2b3ceabdf80cf1fe28cabdcef63246d3cdb5d528` |
| `index_changes/pdf/ind_prs11122025.pdf` | `https://niftyindices.com/Press_Release/ind_prs11122025.pdf` | `fe0137becd78f2771f448f19a85943ceaf5952375608c14094dda327d80d7091` |
| `index_changes/pdf/ind_prs13072026_1.pdf` | `https://niftyindices.com/Press_Release/ind_prs13072026_1.pdf` | `9787f269558fe9c112011671615700ae9effaec482aad18bfafeeb477104286e` |
| `index_changes/pdf/ind_prs13112025.pdf` | `https://niftyindices.com/Press_Release/ind_prs13112025.pdf` | `57dd346835e402f5f5384672f7f7beb71ddf4d67e1af604251fa2ce27b286ea4` |
| `index_changes/pdf/ind_prs15092025_1.pdf` | `https://niftyindices.com/Press_Release/ind_prs15092025_1.pdf` | `3e7fc25c2e90266a8201f31794595cb0855a3d9a6eb06d5437fd1a0c94112881` |
| `index_changes/pdf/ind_prs17032025.pdf` | `https://niftyindices.com/Press_Release/ind_prs17032025.pdf` | `0e34d011886b0fd8142b7bde5c1cf345bd3816d18bee3ae3ee7558db727e9d9c` |
| `index_changes/pdf/ind_prs21022025.pdf` | `https://niftyindices.com/Press_Release/ind_prs21022025.pdf` | `1b3a52abf5954f4b213f5b555ee8776ff596f0adde0612cfdd5409b109195370` |
| `index_changes/pdf/ind_prs22082025.pdf` | `https://niftyindices.com/Press_Release/ind_prs22082025.pdf` | `731113af85aad6b54cce359d5465d84e6062b28b03c21cd9922a20a3f44d2de1` |
| `index_changes/pdf/ind_prs23022026.pdf` | `https://niftyindices.com/Press_Release/ind_prs23022026.pdf` | `cb5830aff1e8715997d9204509315f393ed961838ebc14e986fcb800c62e5a0b` |
| `index_changes/text/ind_prs04042025_2.txt` | DERIVED: `pdftotext -layout pdf/ind_prs04042025_2.pdf` (poppler 24.02) | `b974bee9de0edb0a895096207d929fbbf6283e08e89569cabeea572dd224d088` |
| `index_changes/text/ind_prs04052026.txt` | DERIVED: `pdftotext -layout pdf/ind_prs04052026.pdf` (poppler 24.02) | `41e1dce111c8f11ef00f9d3045100c9b3f7f7e5e560c07f8cfa46b0e55337deb` |
| `index_changes/text/ind_prs04102024.txt` | DERIVED: `pdftotext -layout pdf/ind_prs04102024.pdf` (poppler 24.02) | `cd8e0fb818ee12841f75d06f7f8a0f134ef9ae415d4f981ffe9ed657ceef6866` |
| `index_changes/text/ind_prs10082026.txt` | DERIVED: `pdftotext -layout pdf/ind_prs10082026.pdf` (poppler 24.02) | `71a168b555d6112d053824234ebe82ff20372458f98d9ce3c5fa57861f1b7177` |
| `index_changes/text/ind_prs10102024.txt` | DERIVED: `pdftotext -layout pdf/ind_prs10102024.pdf` (poppler 24.02) | `5d3b977647882e973f8f70f2573032a743fa6290c528fbad41d160b3f8de4dd5` |
| `index_changes/text/ind_prs11122025.txt` | DERIVED: `pdftotext -layout pdf/ind_prs11122025.pdf` (poppler 24.02) | `eb84a22f833557c6481b325db18bb7a93e80dfe10adf8c70488efffff04cde1c` |
| `index_changes/text/ind_prs13072026_1.txt` | DERIVED: `pdftotext -layout pdf/ind_prs13072026_1.pdf` (poppler 24.02) | `7db720a8321453d764877f93d40dd27705fc995cc1cb1b13212296a6dfc34992` |
| `index_changes/text/ind_prs13112025.txt` | DERIVED: `pdftotext -layout pdf/ind_prs13112025.pdf` (poppler 24.02) | `2a69d3918adfff04469e4ceed865c001e86e8caabca3e102ed7941618c3e9ab6` |
| `index_changes/text/ind_prs15092025_1.txt` | DERIVED: `pdftotext -layout pdf/ind_prs15092025_1.pdf` (poppler 24.02) | `c776dd1363c45d1b8224f4c17c005391a8d8e2cbd2338097dd5f0eaeaa25f911` |
| `index_changes/text/ind_prs17032025.txt` | DERIVED: `pdftotext -layout pdf/ind_prs17032025.pdf` (poppler 24.02) | `35fc8fb8ead30b18419824c13dadffd18177eb4f62c19544848878ac2efc1b18` |
| `index_changes/text/ind_prs21022025.txt` | DERIVED: `pdftotext -layout pdf/ind_prs21022025.pdf` (poppler 24.02) | `92c110481d93c8c0789c89aef12644051037e5707fd12d90520567111a28f108` |
| `index_changes/text/ind_prs22082025.txt` | DERIVED: `pdftotext -layout pdf/ind_prs22082025.pdf` (poppler 24.02) | `6609f3ddc3170e0ffefaa19143ffe1761ce42bee394f8ca674b33bb7b5fc275a` |
| `index_changes/text/ind_prs23022026.txt` | DERIVED: `pdftotext -layout pdf/ind_prs23022026.pdf` (poppler 24.02) | `0d3fa8dfc9f8cc88cde441d08a6e7fad336f9eae5a3813c09fcf45bdc60fa875` |

## Phase 2 evidence XBRL (fetched 2026-11-13; discovered via the NSE APIs in references A8)

| File | Archetype / issuer | Period | Source URL | SHA-256 |
|---|---|---|---|---|
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1742038_19102026075842_WEB.xml` | Lending NBFC: Bajaj Finance (BAJFINANCE), Standalone | Q2 FY27 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1742038_19102026075842_WEB.xml` | `d44c672880faffd38c1761737f55f730e3762b24ac9bd4a8f576f1e21923ddd3` |
| `xbrl/INTEGRATED_FILING_LI_1739355_15102026072525_WEB.xml` | Life insurer: HDFC Life (HDFCLIFE), Standalone | Q2 FY27 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_LI_1739355_15102026072525_WEB.xml` | `1ab2d7fdd995469d49d1d155ad33d26362b63c7d30db7a4346e7470603335fd1` |
| `xbrl/INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml` | Consolidated corporate with NCI: Reliance (RELIANCE) | Q2 FY27 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1750537_30102026093254_WEB.xml` | `5e596d6e3dc2941d060bcb95585708f9b1bc3e892db9ab27cc7c03fd9513f758` |
| `xbrl/INTEGRATED_FILING_BANKING_1740912_17102026054806_WEB.xml` | H1 bank with balance sheet: HDFC Bank (HDFCBANK), Standalone | Q2/H1 FY27 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_BANKING_1740912_17102026054806_WEB.xml` | `8dddcb835403be82ccf2bf8cea87cc0c1f64d66652a505eb7b273986f10a94f7` |
| `xbrl/AR_XBRL_ELIN_30092025131606.xml` | Reg. 34 annual report XBRL: ELIN, Standalone | FY2024-25 | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ELIN_30092025131606.xml` | `764ff38562a498e64be60fada42289b3e214d1d9912f42c185c7040569c01309` |
| `xbrl/SHP_1742713_21102026021326_WEB.xml` | Reg. 31 with promoter pledges: Afcons Infrastructure (AFCONS) | 2026-09-30 | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1742713_21102026021326_WEB.xml` | `63a5f445b5c559fa97fc7d802e790ebf94b95111c302435747abf50dd8560093` |

## Mandate 2 stress-test fixtures (representative files only; the full batch is summarised in docs/tag_registry.yaml)

| File | Why it is here | SHA-256 |
|---|---|---|
| `xbrl/INTEGRATED_FILING_INDAS_1751354_02112026065539_WEB.xml` | B1: ITC Q2 FY27 standalone. Excise duty only as a labelled other-expenses line (X40) | `2b76303a83671a849b9701cdc03e81e233aedf3075d27f022b1655d717e76005` |
| `xbrl/INTEGRATED_FILING_INDAS_1748218_28102026075349_WEB.xml` | B1: United Spirits Q2 FY27 standalone. Excise 53% of gross revenue (X40) | `42ba2cdcf272db4e055fbf3430d12b60f3d932fe43b91471ae3b1b48073b3ac3` |
| `xbrl/INTEGRATED_FILING_INDAS_1753920_05112026063545_WEB.xml` | B1: ONGC Q2 FY27 standalone. Lease label with typo "Lease Liabilties" (X39) | `c63b1484dcf638cd44c80a8a06dd91daf66635ec111ba68f6329f712a9963ab4` |
| `xbrl/INTEGRATED_FILING_INDAS_1756234_11112026070341_WEB.xml` | B2: Tata Power Q2 FY27 consolidated. Regulatory deferral movement, associates after PAT(continuing), owners/NCI split (X42) | `05f6dfb5a483496b3fc529b3ce8cb916248ecfbe73e7f1b62a84a83a0522d714` |
| `xbrl/INTEGRATED_FILING_INDAS_1734607_08102026100810_WEB.xml` | S: TCS Q2 FY27 consolidated (Screener parity, NCI) | `613039552dfbe7ac779ef62340b5df844da05c3a2c8a2d943c69cf6fe862353c` |
| `xbrl/INTEGRATED_FILING_INDAS_1751357_02112026065559_WEB.xml` | S: ITC Q2 FY27 consolidated (excise, exceptional, associates placement S3) | `23b97727608d7fa2cdb89ac5a898f01f6f5da75b8fbec07101b25553b3d62a8e` |
| `xbrl/INTEGRATED_FILING_INDAS_1753872_05112026061939_WEB.xml` | S: ELIN Q2 FY27 consolidated (exceptional in Other Income S2) | `9b8e2bccfc59632da33a8b715d78eb7e1fdd5bf30eee5315b6259874dbf52fff` |
| `xbrl/INTEGRATED_FILING_INDAS_1743410_21102026064843_WEB.xml` | S: Eternal Q2 FY27 consolidated (new-gen tech) | `9a010ed527323be9fa116f264e9f62665f16af3eae90100b160155ccc98431ee` |
| `xbrl/INTEGRATED_FILING_BANKING_1740913_17102026054812_WEB.xml` | S: HDFC Bank Q2 FY27 consolidated (bank exceptional S4) | `41840bebf50eacb915fe9ddd2d7cd2bace3d6fffdaa0898a482bd56ddd94aa3b` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1742040_19102026075918_WEB.xml` | S: Bajaj Finance Q2 FY27 consolidated (S5) | `3de881019f229f5fde8d2aa113ea1c71304f5225ebe6a4d192b5f4a65f54ea34` |
| `xbrl/INTEGRATED_FILING_LI_1739360_15102026072721_WEB.xml` | S: HDFC Life Q2 FY27 consolidated (S6) | `d6058876141b32251fdc2d557b2987ca31fffc89ffaddeb472d7ad6288897b54` |
| `xbrl/INTEGRATED_FILING_GI_1740432_16102026073544_WEB.xml` | S: ICICI Lombard Q2 FY27 standalone, Revision of 1738196 (S7) | `5e8d56b54e5fa87989d789fa01abe151d5356abc095fef36395d9c918d3e744c` |
| `xbrl/INTEGRATED_FILING_INDAS_1672621_25052026073245_WEB.xml` | S10: ELIN Q4 FY26 consolidated (FY P&L/BS/CF) | `39ce72ba7222bea08b656fcc2b375bcd4263873008bbbd4d875f32bf4358b0d3` |
| `xbrl/INTEGRATED_FILING_INDAS_1648408_09042026114218_WEB.xml` | S10: TCS Q4 FY26 consolidated (DTA/DTL netting, leases in borrowings) | `17d9c6bb6ac7de632e5558dc2442cbb509b978cce481ff1ed8362b8a8f557cc9` |
| `xbrl/INTEGRATED_FILING_INDAS_1670766_21052026063229_WEB.xml` | S10: ITC Q4 FY26 consolidated (ROU, investment property, equity-method investments) | `366b95ff7cc75b499c447ad0852d8d02233cd290ad4d0fad06b4269480fb23c7` |
| `xbrl/INTEGRATED_FILING_INDAS_1658776_24042026105714_WEB.xml` | S11: Reliance Q4 FY26 consolidated (unexplained borrowings residual) | `6b05d2d10220d88055392da3bc30a2bed456d27930ebf57cef7bb0d48b386270` |
| `xbrl/INTEGRATED_FILING_INDAS_1660628_28042026082148_WEB.xml` | X46: Eternal Q4 FY26 consolidated (audit status per context, ROU, FX in CFI) | `dcad4aee5189866b0835428eacc170a0582f131401bf2f54de4b4c815926250a` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1661603_29042026104724_WEB.xml` | X46: Bajaj Finance Q4 FY26 consolidated (audit status per context) | `88a56b7b0ff07e0dd596e8760eddc24d19389ba1a0db205e14ea7e3228b8c7f5` |
| `xbrl/INTEGRATED_FILING_BANKING_1654391_18042026073048_WEB.xml` | S14: HDFC Bank Q4 FY26 consolidated | `de471a6c3e9af6fa4b93c229f53ce77244eaf664db91b9f0039b6d93472ee3f1` |
| `xbrl/INTEGRATED_FILING_INDAS_1743533_21102026080703_WEB.xml` | B3: SRF Q2 FY27 consolidated (4 segments, power & fuel, FX label) (X49, X50) | `6c3c9ed3156134b3a18f1bd96184c7681670472bfdcad0ce96b6648de3caf0c1` |
| `xbrl/INTEGRATED_FILING_INDAS_1753292_04112026105837_WEB.xml` | B3: Cummins India Q2 FY27 consolidated (segment totals differ from P&L; associates in segment PBT) (X49) | `eef0b34d138851d2b8f32af4167c830288484a316eaae5db1673706f47b6bbd5` |
| `xbrl/INTEGRATED_FILING_INDAS_1746046_26102026055540_WEB.xml` | B3: APL Apollo Q2 FY27 consolidated (zero-attribution placeholder) (X48) | `11d50f34e32dbb0c81a0493a5152f25149395ad2f0d92bf2a8dbe4eaffcc33ba` |
| `xbrl/INTEGRATED_FILING_INDAS_1751861_03112026045154_WEB.xml` | B3: AIA Engineering Q2 FY27 consolidated (power & fuel, freight labels) (X50) | `fbaf195682b0c97792869addd546571f29436b4f9280662eb677d644ad543069` |

Source URL pattern for all twenty-three: `https://nsearchives.nseindia.com/corporate/xbrl/<file>`.

## Screener goldens (local only, not committed)

The repository is public, so the user-supplied Screener Excel exports (2026-11-13) and their extracted Data Sheets are
**not** committed. Re-create them with `python scripts/extract_screener_golden.py EXPORT.xlsx ... --out data/screener_golden`
(`data/` is gitignored). The parity harness carries only the specific figures it asserts. Hashes:

| Export sha256 | Extracted JSON sha256 | File |
|---|---|---|
| `1ecda3744f11079c2fad5b00f458efc576da42a1f7a2c3259e133d5715cc686b` | `bdd7e4b2d370ef6f1183dee5c3ddb397ed3b5ee405824ee47ef5e90adc4b7dc3` | `TATA_CONSULTANCY_SERVICES_LTD.json` |
| `08a48ee253914da355241b8022a7cc8db98a3725f4339575862421d1dc19182b` | `b5c833ba3a63f737a14a867c930b6985604de88e07db53456116ae05f4ec3d2e` | `ELIN_ELECTRONICS_LTD.json` |
| `99ef74f02f51cc2c40218d824b9dfc6a668e836e931364a70b4a46a4a0d8ca79` | `bac1d0d7702d34e1d6af37f3ef181a0c60f29defb802c9304dfefdebfb596bc5` | `ITC_LTD.json` |
| `05b25df6981044b0d7fb556aac4f68c77da1b62247e74d6bbe18f59fd9dedbda` | `4eaad51e02e1657170df89a820ca49af1950668274bdaacff23236e57d366ae1` | `BAJAJ_FINANCE_LTD.json` |
| `14163f4d412e18c51d3f45cf169701effd596f7da62dbb7f6df4e06ef086ed05` | `0d5f39c0d92834c4c5f37ed2f9e476fe1b676d289ba198b8b5dd8f482de02b45` | `TATA_MOTORS_PASSENGER_VEHICLES_LTD.json` |
| `a3987966d0824c6b96439e0daefe75d114d9947fd12750082268763d8824bc21` | `97c07878e56b14d32d210016c30892684196c5aa949c397b64ec1184dafbf839` | `ETERNAL_LTD.json` |
| `67d37e45fa0c5daf478f4a868ac7055df8303e0d1906bd9c79eae458f1c8a829` | `e2737a83e14713ac99ffef3e08d6ce56e7aaa015ba4ebfad6bc65c1e63e7cf12` | `HDFC_LIFE_INSURANCE_COMPANY_LTD.json` |
| `c4bac255a4bda4f329da9006503be15d9108da123a3a8a9457e3a99fad20446c` | `785856a89daffa802ef36c08371c58f479a0267d06872cc92a5f87b78b0685d0` | `TATA_MOTORS_LTD.json` |
| `e047fb373a15866a2e5541228275c2142c5f2c42046d7094fe953f1ec49f8230` | `2e36ebf3a8eabefd54f3852240e09a0972cbf26d36ad02960f8a9dcc39026597` | `HDFC_BANK_LTD.json` |
| `042a2d466e5c83a1e37afa3ef87cdfd9628d129b935f616f0aeda0d7b93e56aa` | `a4506402ac2543848c020db3f82e066dc46272d492a369e17352f5a588fb5b2a` | `RELIANCE_INDUSTRIES_LTD.json` |
| `75e82a7bb887382e94d44dcb9609fce829b17da55680f7d7adae6861d151eeeb` | `5efd6240d6d4d9e8128be1bf03634d67a0043f239bc1a9e0c8738c1bc3407dd3` | `STAR_HEALTH___ALLIED_INSURANCE_COMPANY_LTD.json` |
| `30f81d594b343e2a295d39530680d7abb619d94a4217680a784ea63b4d148335` | `0c8360fa1de536885cacbc34ab699611f72f937ef65d5f61737bfa29cd22b4e9` | `ICICI_LOMBARD_GENERAL_INSURANCE_COMPANY_LTD.json` |
