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
| `xbrl/INTEGRATED_FILING_INDAS_1574923_14112025041850_WEB.xml` | X52: TMPV Q2 FY26 consolidated (demerger scheme gain tagged discontinued) | `0b15b25ebbd5de3e662d5305b9890f931dd6c5b7a951717eb8f88fc43d401d32` |
| `xbrl/INTEGRATED_FILING_INDAS_1574016_13112025070452_WEB.xml` | X52/C12: Tata Motors Ltd (CV) Q2 FY26 consolidated, first filing after listing | `c2d5beb1a142ec1769eef2189af5d86ddd6e7b4738863bab30f1fe15ef516c7c` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1750814_31102026080404_WEB.xml` | B4: Muthoot Finance Q2 FY27 consolidated (gold-loan NBFC; leases labelled) (X54, X57) | `c59af915c0c3fc83eb57a7859332daae9d39b2628c2562491240fcb0a49ca8e2` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1748226_28102026075925_WEB.xml` | B4: PNB Housing Finance Q2 FY27 consolidated (HFC; deposits; impairment write-back; zero-attribution 2nd observation) (X55, X56) | `93df5e99ffadd01d618de9409d92e868ff11a800a9cf65a3dd2daa5692c5066b` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1748395_28102026112856_WEB.xml` | B4: Cholamandalam Q2 FY27 consolidated (owners profit tagged as TCI: quarantined) (X56) | `5c89348137ac6f3fa16d8b7fa3b2097f9b5954047f399810680479038c262493` |
| `xbrl/INTEGRATED_FILING_BANKING_1740465_16102026082727_WEB.xml` | B5: Punjab National Bank Q2 FY27 standalone (PSU; H1 balance sheet; AT1; GoI 70%) (X58, X59) | `96970acc7a4cd1bcffc5d46d8c10858291c925bfc9370b5434c36cc4a8e29330` |
| `xbrl/INTEGRATED_FILING_BANKING_1699404_22072026053243_WEB.xml` | B5: IndusInd Bank Q1 FY27 standalone (no balance sheet; AT1 = 0 real) (X58, X59) | `8bbfb8ececb45a687d182deca64f7dfba95312079200feb0c4ee74a86515283d` |
| `xbrl/INTEGRATED_FILING_BANKING_1745379_24102026050751_WEB.xml` | B5: Kotak Mahindra Bank Q2 FY27 standalone (face value mis-tagged 994.79) (X61) | `a40e30c3ba7d7bd97900783ca4424e57696b4d1dc5601675b6f5a29b81e424b1` |
| `xbrl/IF_INS_COM_IND_AS_19799_WebXMLFile_20261027_212749295.xml` | B6: Star Health Q2 FY27 standalone, Ind AS 117 (one of 5 byte-identical broadcasts) (X64) | `903eb86889821e81daa7c432ec46b6a129d30e35a109e8ecafe8b198fd961210` |
| `xbrl/INTEGRATED_FILING_LI_1747186_27102026072642_WEB.xml` | B6: SBI Life Q2 FY27 standalone (solvency in times; persistency) (X62, X65) | `54156e0c102988a9b1ad4546c27e5efd2621e3e25c919150b4d97418f834ba6f` |
| `xbrl/INTEGRATED_FILING_GI_1750325_30102026070447_WEB.xml` | B6: New India Assurance Q2 FY27 standalone (PSU; memo provisions; solvency /100) (X63, X65) | `d7efe24db84a2121a1b2f8426e024363719bcd71f1eaae30499a65ac5122d03a` |
| `xbrl/INTEGRATED_FILING_BANKING_1740466_16102026082756_WEB.xml` | S19: Punjab National Bank Q2 FY27 consolidated (Screener parity) | `70f3870720a0ccc6740ad1bdf31db02018a0f5b2df9d9524c00dabc9a69f4bd9` |
| `xbrl/INTEGRATED_FILING_BANKING_1745380_24102026050818_WEB.xml` | S19: Kotak Mahindra Bank Q2 FY27 consolidated (Screener parity) | `e5f8dd57cfadb16f256c66e1b18042c4a17de3a49367c7b33638d64bee55918e` |
| `xbrl/INTEGRATED_FILING_GI_1750334_30102026070831_WEB.xml` | S18: New India Assurance Q2 FY27 consolidated (NP residual) | `5f91d2500070f665aadb838eb6c51fe4473329422a16ab9af65a0cd31f5150fb` |
| `xbrl/INTEGRATED_FILING_BANKING_1699401_22072026052845_WEB.xml` | S19: IndusInd Bank Q1 FY27 consolidated (Screener parity) | `f06b27fbb453b90c297854563c56cfe7eba232ed9a9f88fbf50c175481ef4030` |
| `xbrl/INTEGRATED_FILING_INDAS_1750535_30102026093155_WEB.xml` | S19: Reliance Q2 FY27 standalone (Screener standalone view) | `9c426dd82ce4a59cb55bcb25f0f19799e1d1250a80aa6b07efd0562a3e897a27` |
| `xbrl/INTEGRATED_FILING_INDAS_1750274_30102026064310_WEB.xml` | X67: Delhivery Q2 FY27 consolidated (owners tagged as TCI, 2nd observation) | `8c235397849928abe102bdd483362fea7f5c4b96d84b007bfe82d06a3541cc34` |
| `xbrl/INTEGRATED_FILING_INDAS_1752762_04112026053637_WEB.xml` | S20: Nykaa (FSN) Q2 FY27 consolidated | `4fe1d98c814a9d04c9c929041c256cfa7b28f246f481ff35aa2fc9279a112373` |
| `xbrl/INTEGRATED_FILING_INDAS_1747783_28102026044327_WEB.xml` | S20: Info Edge Q2 FY27 consolidated | `ab0c46ba76a34a5ea116c2e982cc920be02300ad5a4bd407ddefa2b2eb71beaf` |
| `xbrl/INTEGRATED_FILING_INDAS_1747782_28102026044245_WEB.xml` | S20: Info Edge Q2 FY27 standalone | `0859c66044f13557a26a9b43cdcc8149732d769b90d758559209134f20649d96` |
| `xbrl/INTEGRATED_FILING_INDAS_1756932_12112026075230_WEB.xml` | X67: Ola Electric Q2 FY27 consolidated (owners sign flip: quarantined) | `1f1860ffdb293db57aa9b172d74eedb752920817b2bd3a440993f61d0a323b66` |
| `xbrl/INTEGRATED_FILING_INDAS_1746348_26102026105317_WEB.xml` | X68: Paytm (One 97) Q2 FY27 consolidated (ESOP, contract liabilities, marketing) | `28a86c6dd1a88f4b53945b08b7ccdbb9065c599362b31f90503feb0346369775` |
| `xbrl/INTEGRATED_FILING_INDAS_1750589_30102026112529_WEB.xml` | S20: PB Fintech Q2 FY27 consolidated | `323ac0869089a8306d94eae266294af5cbaff249394b96974237305f4f279cf4` |
| `xbrl/INTEGRATED_FILING_INDAS_1744176_22102026064114_WEB.xml` | S20: Swiggy Q2 FY27 consolidated | `746a497cc2fe310fbe9055d0c0af865837487a95c918a14b91279f76b564f5b3` |
| `xbrl/INTEGRATED_FILING_INDAS_1747309_27102026112939_WEB.xml` | X68: IndiaMART Q2 FY27 consolidated (contract liabilities) | `7207e7cc4e93a69e34a7ab33d21bf728022a19ad67a5ebfa30102c7c13f0b0c1` |
| `xbrl/INTEGRATED_FILING_LI_1736933_13102026040430_WEB.xml` | X66: ICICI Prudential Life (ICICILIFE) Q2 FY27 standalone | `9a072928dc9d4c0167e0c8d4428216b35a9d429382face5ed7bc64065d67fcda` |

Source URL pattern for all forty-nine: `https://nsearchives.nseindia.com/corporate/xbrl/<file>`.

## Batch 8 Reg. 31 shareholding (fetched 2026-11-13 via the NSE master JSON [SHP6], one file per request)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/SHP_1733480_06102026050037_WEB.xml` | B8: HDFC Bank 2026-09-30. No promoter category (SHP11); DR custodian + EBT in NPNP (SHP8, SHP9) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1733480_06102026050037_WEB.xml` | `c80d08919f28aaa72c760befd872a9ffb2b4f1bc34197238fcaa100c72af3e74` |
| `xbrl/SHP_1687801_03072026023346_WEB.xml` | B8: HDFC Bank 2026-06-30. Previous quarter for fii_dii_qoq_change_pct (SHP14) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1687801_03072026023346_WEB.xml` | `61753bad377afabb41daad2740027f6e1a4bc918bd8ee0a0176bfebf02847d1a` |
| `xbrl/SHP_1743956_22102026042725_WEB.xml` | B8: ICICI Bank 2026-09-30. No promoter; ADRs as overseas depositories inside Institutions (Foreign) (SHP13) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1743956_22102026042725_WEB.xml` | `c92a1b37d78bac1a36f9c74547201bc78f78f5fdf90ec43d068fab5ff4aa0b7f` |
| `xbrl/SHP_198754_1421266_21042025041033_WEB.xml` | RELIANCE 2025-03-31 (Q4 FY25), 2022-09-30 taxonomy: entity contexts OneD/OneI undeclared, percent-point percentages, `Catergory` FPI member (SHP16, SHP18) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_198754_1421266_21042025041033_WEB.xml` | `d8142206f412ec506b72f1f4387f8d70c4de151ff31d265d8766f9e4da92b4bf` |
| `xbrl/SHP_1489727_21072025081003_WEB.xml` | RELIANCE 2025-06-30, 2025-05-31 taxonomy with TOTAL pct `100.00`: percent points inside the newer taxonomy (SHP18) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1489727_21072025081003_WEB.xml` | `78409c0d7a0ffb690d2f128b3837cb06349f28ee6d50a585abb76c7a5947069c` |
| `xbrl/SHP_1643664_30032026100841_WEB.xml` | CMPDI pre-listing pattern: DateOfReport 2026-03-25, every category context on DateOfListing 2026-03-30 (SHP17) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1643664_30032026100841_WEB.xml` | `7f53a12e474c08bd78d503a26fa5e991cf96a918ff798f18f3e76dcfe722ba7e` |
| `xbrl/SHP_1600790_14012026043343_WEB.xml` | ECLERX allotment pattern: DateOfReport 2026-01-09, every category context on DateOfAllotment 2026-01-07 (SHP17) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1600790_14012026043343_WEB.xml` | `d0fd189bc5584458c90ebbc54b28ecccff8dcb43ce2751a1dbf306a8f0bc8f88` |
| `xbrl/AR_XBRL_ACUTAAS_30102025113233.xml` | ACUTAAS FY25 standalone Reg. 34 annual: owners' and NCI share both 0 against PAT 1,595,462,000 (X48 in an annual filing) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ACUTAAS_30102025113233.xml` | `8b0c674bc7ea09016f9c6c4e8c73d6d57126d487e570322d155a581d77ec2785` |
| `xbrl/INTEGRATED_FILING_INDAS_1506803_08082025045458_WEB.xml` | Tata Motors Q1 FY26 standalone (quarter as first filed, before the CV demerger re-presentation) (X80) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1506803_08082025045458_WEB.xml` | `5f1018e4d6508385f1d54a75ecec9f5d0e1613583c2f5438392901ea749fc8fb` |
| `xbrl/INTEGRATED_FILING_INDAS_1574914_14112025041626_WEB.xml` | Tata Motors Q2 FY26 standalone: H1 revenue YTD 23,993 cr vs Q1 + Q2 as filed 28,637 cr (X80) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1574914_14112025041626_WEB.xml` | `c28d844838298d23a158fd0221f766bfc55b1c8c4c25aa937bd33476c37f0768` |
| `xbrl/INTEGRATED_FILING_INDAS_1619042_05022026042048_WEB.xml` | Tata Motors Q3 FY26 standalone: 9M revenue YTD 39,261 cr vs quarters 43,905 cr (X80) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1619042_05022026042048_WEB.xml` | `8d4814f469272f587d82f435bf107e08e39da192a84e8a384c750614a27b1377` |
| `xbrl/INTEGRATED_FILING_INDAS_1667176_14052026062559_WEB.xml` | Tata Motors Q4 FY26 standalone: FY revenue 57,859 cr vs quarters 62,503 cr (X80) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1667176_14052026062559_WEB.xml` | `96a477c4abb164ace72eb5d16afd2bb0f3368f93e9e3f48a44be0ac8f3eec95b` |
| `xbrl/INTEGRATED_FILING_INDAS_1511655_13082025060450_WEB.xml` | AVANTIFEED Q1 FY26: stated ISIN `INE871CO1038` (letter O for 0) of INE871C01038 (X81) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1511655_13082025060450_WEB.xml` | `81d5f8ebea9664087b75cfa952eb916062910368c95abf671f92bf17a9b31d5f` |
| `xbrl/INTEGRATED_FILING_INDAS_1489565_21072025071304_WEB.xml` | OBEROIRLTY Q1 FY26: stated ISIN `INE903I01010` (adjacent swap) of INE093I01010 (X81) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1489565_21072025071304_WEB.xml` | `960abcc0c16252cdc5848ea1a6a842801e8421e897c4c943047053b01eaa6ab7` |
| `xbrl/INTEGRATED_FILING_INDAS_1603408_17012026050918_WEB.xml` | NETWEB Q3 FY26 standalone: Oct-Dec quarter and Apr-Dec YTD, the quarter the Oct-Mar context would be bridged against (X82) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1603408_17012026050918_WEB.xml` | `9b20406d63bf2db13cf563f86a9ffac862d04a8f694c1fe1d5257c946c0b3af4` |
| `xbrl/INTEGRATED_FILING_INDAS_1663034_02052026072054_WEB.xml` | NETWEB Q4 FY26 standalone filed as `TypeOfReportingPeriod` "Half Yearly" / `ReportingQuarter` "Yearly": the Jan-Mar quarter (PAT 705,930,000) sits in an Oct-Mar context (X82) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1663034_02052026072054_WEB.xml` | `58965e306312405bb86686af3650c19a8c013d7e63c04f4116a0bdc64f2a7273` |
| `xbrl/INTEGRATED_FILING_INDAS_1668217_16052026103806_WEB.xml` | NETWEB Q4 FY26 standalone re-filed on 16 May 2026 as "Fourth quarter": the same 705,930,000 in a Jan-Mar context (X82, X83) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1668217_16052026103806_WEB.xml` | `3057b3f95ef25aea3847ca592bd87db1772b808ca98c71911fb2eed28c7b30e2` |
| `xbrl/INTEGRATED_FILING_INDAS_1662399_30042026063302_WEB.xml` | Adani Ports Q4 FY26 consolidated: owners / NCI profit elements carry the OCI attribution (1,238.67 / 179.14 Cr); the results PDF reads 3,328.96 / (20.66) Cr = TCI attribution minus OCI attribution (X84) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1662399_30042026063302_WEB.xml` | `71fef667d312206ce7e90a78460f0163817fcc3809374b843e930d9287300549` |
| `xbrl/INTEGRATED_FILING_INDAS_1754829_06112026051018_WEB.xml` | Godrej Agrovet Q2 FY27 consolidated: H1 NCI filed +18.65 Cr where owners - NCI = PAT 231.06 Cr (X85) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1754829_06112026051018_WEB.xml` | `a9d4e5eb22a955312616b4d3b7fc61b9a15970cdd426a6deba8ce3330ea3c126` |
| `xbrl/INTEGRATED_FILING_INDAS_1663900_05052026095708_WEB.xml` | Coforge Q4 FY26 consolidated: owners + NCI = TCI (633.0 Cr), not PAT (666.2 Cr); OCI split untagged, so the split is withheld (X86) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1663900_05052026095708_WEB.xml` | `b62df1c66527bef2be46fd82cf1ad7a89318d102407403d9f15c00f82ffc4915` |
| `xbrl/INTEGRATED_FILING_INDAS_1662668_30042026100228_WEB.xml` | Godrej Agrovet Q4 FY26: stated ISIN INED50D01014 (D for 8; security INE850D01014), symbol GODREJAGRO; issuer code differs, name agrees (X88) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1662668_30042026100228_WEB.xml` | `b04664b15f64c84bdf21e1d56363f1dd241c9d963ca959e0007979d79b4d1101` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1483684_15072025082343_WEB.xml` | HDB Financial Q1 FY26: stated ISIN INE756I08058 is its own bond ISIN (equity INE756I01012), symbol HDBFS (X88) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1483684_15072025082343_WEB.xml` | `6af8a85b1e1b316b7026758fd3ff44337f485f1f799adb58c9f2fad0439780ce` |
| `xbrl/INTEGRATED_FILING_INDAS_1491776_23072025083000_WEB.xml` | Persistent Systems Q1 FY26: stated ISIN INE262H01016 is the pre-split ISIN (now INE262H01021), symbol PERSISTENT (X88) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1491776_23072025083000_WEB.xml` | `7c059b5135f2c95a0f292e65b64e1b62f4d9ad72d8d930c74f2f693b7f2345ab` |
| `xbrl/INTEGRATED_FILING_INDAS_1487244_18072025075933_WEB.xml` | MRPL Q1 FY26 standalone on the non-Ind AS template (IntegratedFinance_OtherThanBank), 18 Jul 2025 (X89) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1487244_18072025075933_WEB.xml` | `5fedd8300ddad4f2de502e24d9b859561c91fb06807d19ef7753a3aa44521879` |
| `xbrl/INTEGRATED_FILING_INDAS_1487257_18072025080410_WEB.xml` | MRPL Q1 FY26 consolidated on the non-Ind AS template (IntegratedFinance_OtherThanBank), 18 Jul 2025 (X89) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1487257_18072025080410_WEB.xml` | `a3673c8e666d067aaf775fdb4a9e42b8a7b9fc8daecdc346e4da6441396fa0dd` |
| `xbrl/INTEGRATED_FILING_INDAS_1487538_19072025125012_WEB.xml` | MRPL Q1 FY26 standalone re-filed on the Ind AS template, 19 Jul 2025 (X89) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1487538_19072025125012_WEB.xml` | `af396e23bb4d14f3204f272b55679b5c574bdbd58e57c0f56114776455260cba` |
| `xbrl/INTEGRATED_FILING_INDAS_1487540_19072025125103_WEB.xml` | MRPL Q1 FY26 consolidated re-filed on the Ind AS template, 19 Jul 2025 (X89) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1487540_19072025125103_WEB.xml` | `4a7111fd423e05578da5b798fd83f00bacf9dce6fc9e57c42ead068e5caf340b` |
| `xbrl/INTEGRATED_FILING_GI_1700274_23072026063349_WEB.xml` | Go Digit Q1 FY27 on the IRDAI Indian-GAAP general-insurer template (PBT 115.45 Cr); Q2 FY27 moved to Ind AS 117 (X90) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_GI_1700274_23072026063349_WEB.xml` | `0a7057002000cd82e82c6e463fd19b1454c5c4f612179071d210f324fb00bb35` |
| `xbrl/INTEGRATED_FILING_INDAS_1492889_24072025091201_WEB.xml` | ACC Q1 FY26 consolidated: owners + NCI = TCI 368.88 Cr with NCI 0.04 Cr; PDF owners 375.38 = PAT - NCI (X92) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1492889_24072025091201_WEB.xml` | `926c7d7c519328ab1d027edd238e00cbb296fb0923a95a8ce77edb8eba4ee3e3` |
| `xbrl/INTEGRATED_FILING_INDAS_1551863_17102025035733_WEB.xml` | Atul Q2 FY26 consolidated: owners + NCI = TCI; PDF owners 179.24 (Q) / 307.01 (H1) Cr = PAT - NCI (X92) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1551863_17102025035733_WEB.xml` | `14156ba9354279aac96a228ac6337eb6c26ade883118364b465167efdcba0324` |
| `xbrl/INTEGRATED_FILING_INDAS_1749418_29102026084017_WEB.xml` | Brigade Q2 FY27 consolidated (Lakhs): owners / NCI carry the TCI split; PAT - NCI = 193.62 vs PDF 193.60 Cr (X92) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1749418_29102026084017_WEB.xml` | `c6c702f60359435711fabe3db3094d97f49b8fa2e26bfb187f583bc57d96af21` |
| `xbrl/INTEGRATED_FILING_INDAS_1562886_31102025071826_WEB.xml` | Intellect Design H1 FY26 consolidated (Millions): NCI filed = PAT 1,956.13; PDF NCI (11.47) = PAT - owners (X91) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1562886_31102025071826_WEB.xml` | `6f8c732c344b49d48af00eed8f4a0fa7a8f8545f87db4aee0b309b30c74c5cb6` |
| `xbrl/INTEGRATED_FILING_INDAS_1710906_10082026025320_WEB.xml` | SPARC Q1 FY27 (Lakhs): owners -20.76 vs PAT -20.78 Cr, NCI 0; the PDF shows the same 2-lakh gap (X93) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1710906_10082026025320_WEB.xml` | `dd68e0a4b4cbe04c7be3874b058221362c3caff43f0eebdb29334c5a85e9fc28` |
| `xbrl/INTEGRATED_FILING_INDAS_1435405_09052025091610_WEB.xml` | Reliance Power Q4 FY25 (Lakhs): owners 125.60 vs PAT 125.57 Cr, NCI 0; the PDF shows the same 3-lakh gap (X93) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1435405_09052025091610_WEB.xml` | `3028c10bc4e977c02397c32803203986901b6623258ecb084119abd2030b2948` |
| `xbrl/INTEGRATED_FILING_INDAS_1424350_24042025113829_WEB.xml` | Tech Mahindra Q4 FY25 consolidated: owners + NCI = OCI 206.0 Cr, TCI split untagged; PDF owners 1,166.7 / NCI (24.8) Cr: withheld (X86) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1424350_24042025113829_WEB.xml` | `b13c09f1c62259224fbc1c4a2f68faede37f3888ba10e1c4cbe102b9c46c281b` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1750817_31102026081106_WEB.xml` | Muthoot Finance Q2 FY27 standalone: PBT 3,992.52 Cr current but current / deferred tax 789.25 / 17.02 Cr are Q2 FY26's (PDF: 1,005.04 / 10.86 Cr, PAT 2,976.63 Cr, EPS 74.14); H1 likewise (X94) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1750817_31102026081106_WEB.xml` | `7d13a0693701c98f02baf5555bd7c21f2a55391bff2a62d865ef91d1807276e0` |
| `xbrl/INTEGRATED_FILING_NBFC_INDAS_1574319_13112025084559_WEB.xml` | Muthoot Finance Q2 FY26 standalone: the prior-year filing whose tax lines 1750817 repeats (X94) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1574319_13112025084559_WEB.xml` | `4f9fafa2a8118f520b8d646d2713c924d41c752f831df7fb3f54418450bf1b9e` |
| `xbrl/INTEGRATED_FILING_INDAS_1677062_29052026111208_WEB.xml` | Glenmark Q4 FY26 consolidated: owners / NCI filed swapped (rupees -950,000 / 3,014,140,000); PDF owners 3,014.14 / NCI (0.95) Mn; EPS 10.68 (X95) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1677062_29052026111208_WEB.xml` | `16182948b2edb27a3fdc42b5b6f6b42017ee197d5e4a6b8aafc06cdf7327b55a` |
| `xbrl/INTEGRATED_FILING_INDAS_1444664_20052025064321_WEB.xml` | Zydus Lifesciences Q4 FY25 consolidated: owners 728 / NCI 11,709 Mn filed swapped; PDF owners 11,709 / NCI 728; EPS 11.64 (X95) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1444664_20052025064321_WEB.xml` | `47a7bf34e0566f3655e9b960a6118d6ea509d24e7f15f51a3cbb138ddf67b121` |
| `xbrl/INTEGRATED_FILING_INDAS_1500111_01082025034547_WEB.xml` | Kirloskar Brothers Q1 FY26 consolidated: owners 8 / NCI 667 Mn filed swapped; PDF owners 667 / NCI 8 Mn; EPS 8.40 (X95) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1500111_01082025034547_WEB.xml` | `409453db9cb09cf6fabb6fca3667cd0e9a0c960979cc9a8f4d3a6c5eae1f59ba` |
| `xbrl/INTEGRATED_FILING_INDAS_1660691_28042026092008_WEB.xml` | The Leela (Schloss Bangalore) Q4 FY26 consolidated: owners element = OCI (264.09 / 330.36 Mn), no NCI element filed; PDF owners 1,717.70 / 4,031.34 Mn = TCI owners - OCI (X96) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1660691_28042026092008_WEB.xml` | `9a17767d7767d85b33328fc50b3e62f60335b6ad6940b1883664f2eb6cc6f960` |
| `xbrl/AR_XBRL_CUMMINSIND_04092026113534.xml` | Cummins India FY26 consolidated annual report (Reg. 34): PBT 3,085.95 Cr incl. JV share 266.28 (X100) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_CUMMINSIND_04092026113534.xml` | `01b49c245f8f3f4165289466b96c5cbdff374c016ac88e9acba41e70672bf4b1` |
| `xbrl/INTEGRATED_FILING_INDAS_1674519_27052026092425_WEB.xml` | Cummins India Q4 FY26 consolidated results: FY PBT 2,819.67 Cr excl. JV share (X100) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1674519_27052026092425_WEB.xml` | `97763757655542eb33f9ab6d9b4ea09cbc1df4662613c42294764cc795f2ecfc` |
| `xbrl/INTEGRATED_FILING_INDAS_1498822_31072025011108_WEB.xml` | Gillette India Q1 FY26 standalone: Symbol GILLETTE with P&G Hygiene's ISIN INE179A01014 (X101) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1498822_31072025011108_WEB.xml` | `25409572da5f46ca4732a2ad5df4077bd10a68e54e53e96cb743d8d76030f2e8` |
| `xbrl/INTEGRATED_FILING_INDAS_1510705_13082025092940_WEB.xml` | Finolex Cables Q1 FY26 consolidated: PBT 176.37 Cr before JV share 26.18 (X102) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1510705_13082025092940_WEB.xml` | `cab1645db85432c47a4dceb4343ece45c4d1c87140d8772d59cf964a3e526469` |
| `xbrl/INTEGRATED_FILING_INDAS_1571804_11112025093544_WEB.xml` | Finolex Cables Q2 FY26 consolidated: JV share inside PBT as exceptional 38.11, JV element 0; H1 PBT 408.75 (X102) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1571804_11112025093544_WEB.xml` | `48ccf024a57c03d731d9becf490c746071f3e9044de33dc238dc9dd812681fd4` |
| `xbrl/SHP_1734273_08102026033216_WEB.xml` | Adani Wilmar Reg. 31 at 30-Sep-2026: total 1,299,678,605 shares incl. 7,860,970 held by employee trusts (X103) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1734273_08102026033216_WEB.xml` | `65d9a9c869270c9df4a722be0b8fb867ef1be6c2aa82bbe04b626f95516475ea` |
| `xbrl/INTEGRATED_FILING_INDAS_1747073_27102026063415_WEB.xml` | Adani Wilmar Q2 FY27 results: paid-up / face value 1,291,800,000 = total less trust shares (X103) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1747073_27102026063415_WEB.xml` | `c709d2d21787d99ccf833f9925b432f31e3bf94dc73e7edbe55176b1ece6839b` |
| `xbrl/INTEGRATED_FILING_LI_1600999_14012026055812_WEB.xml` | ICICI Prudential Life Q3 FY26: declared start dates 2025-01-10 / 2025-01-04 = day-month swap of the contexts' 2025-10-01 / 2025-04-01 (X104) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_LI_1600999_14012026055812_WEB.xml` | `5a1a7afaf8e6b13af7e8ab8531fd47e9289141bb874e5df398965ab68654b677` |
| `xbrl/INTEGRATED_FILING_LI_1601820_15012026075716_WEB.xml` | HDFC Life Q3 FY26: same day-month swap of the declared start dates (X104) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_LI_1601820_15012026075716_WEB.xml` | `08dcff200505cf3f4527f50ffb4302d54d53b7a035d6ca901b428cf2f31779a0` |
| `xbrl/INTEGRATED_FILING_INDAS_1475626_01072025025937_WEB.xml` | Premier Energies Q4 FY25 consolidated: owners = TCI, no NCI element (X105) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1475626_01072025025937_WEB.xml` | `d9d6cbc577d121b3ab3cfc990ce1737ea5d4ed1dbbb0ed34f5ad9d2a206c88a6` |
| `xbrl/INTEGRATED_FILING_INDAS_1456174_29052025103806_WEB.xml` | Finolex Cables Q4 FY25 consolidated: owners = NCI = PAT 191.71 Cr (X105) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1456174_29052025103806_WEB.xml` | `c891e1bdfdc424139d9b939fbd2535d1c27905cb06be00a3afd2b3a39397f05a` |
| `xbrl/INTEGRATED_FILING_INDAS_1609091_23012026034910_WEB.xml` | STL Tech Q3 FY26 consolidated: 9M NCI 0, PAT -3 Cr, owners 10 Cr (crore rounding); PDF owners (3) (X105) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1609091_23012026034910_WEB.xml` | `aa3f8fd488c0ba6b0f51ae6b76987b62d7b96df60a58d4d40177ef4dee08a89d` |
| `xbrl/INTEGRATED_FILING_INDAS_1620148_06022026044508_WEB.xml` | Siemens Q3 FY26 standalone: every context on the previous filing's dates (Apr-Jun 2025, Oct 2024-Jun 2025), declared Oct-Dec 2025 and Oct 2024-Dec 2025; PDF revenue 33,985 / 179,167 Mn (X87) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1620148_06022026044508_WEB.xml` | `8e63bf24f6dbfecd058a98de0ddc5ab791c6cc7dec717dddceeae425e038da9b` |
| `xbrl/INTEGRATED_FILING_INDAS_1620200_06022026050905_WEB.xml` | Siemens Q3 FY26 consolidated: same stale context dates (X87) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1620200_06022026050905_WEB.xml` | `cc4619a04188879f01ce14ac7dbc388dab1a574983b7eec4e93cd6a32d8944da` |
| `xbrl/SHP_1740148_16102026052137_WEB.xml` | B8: Vedanta 2026-09-30. NDU + other encumbrance, no pledge (SHP10); EBT in NPNP | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1740148_16102026052137_WEB.xml` | `e1f98ab9a4db78a1b21f2e7b9f90d9cfd7e47e5fd5ec72e9525a9e0630d5eda5` |
| `xbrl/SHP_1743210_21102026055808_WEB.xml` | B8: JSW Steel 2026-09-30. Promoter pledge 12.25%; FDI (JFE) 15% (SHP10, SHP13) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1743210_21102026055808_WEB.xml` | `5a53b46441c60727a6a855b78aeed0a68921201b32ec8661daf86e58541f6bd0` |
| `xbrl/SHP_1733654_07102026112959_WEB.xml` | B8: Apollo Hospitals 2026-09-30. Promoter pledge 2.91%; >1% public holders (SHP10, SHP12) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1733654_07102026112959_WEB.xml` | `4686100c7f9c77b5491aa1576e9a4be3a4d8ddcc988caa05ea628a0615ea0228` |
| `xbrl/SHP_1742520_21102026115715_WEB.xml` | B8: Info Edge (NAUKRI) 2026-09-30. Screener shareholding parity; employee trust as Screener 'Others' (SHP15) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1742520_21102026115715_WEB.xml` | `1a7b188e3940d89ce5c1680a10919329dce743b5b091384cfb2abea0ae431094` |

Inspected for Batch 8 but not committed (registered in docs/tag_registry.yaml):

| File | Company / why | SHA-256 |
|---|---|---|
| `SHP_1736411_12102026064817_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1736411_12102026064817_WEB.xml) | ADANIENT 2026-09-30 (pledge) | `8e0b38f78edf839f987461979869a1b7504a05c815637389080ac9a521591c61` |
| `SHP_1690795_10072026081131_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1690795_10072026081131_WEB.xml) | ADANIENT 2026-06-30 (share-count change, SHP14) | `6d199e3c2ce88c06a937b423c6a3459d3ce7f99bc028686bd69de84054736aa1` |
| `SHP_1738462_15102026105915_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1738462_15102026105915_WEB.xml) | SUNPHARMA 2026-09-30 (pledge) | `dca3e32c0b7595ce0cf2eb14f494c03bd89453234b87bde829aa2805552c1f7f` |
| `SHP_1736151_12102026041358_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1736151_12102026041358_WEB.xml) | MFSL 2026-09-30 (pledge, FDI 21.86%) | `12b056da659c4033bd654662a93519b8ea3c0fc2ee459d10d8566dd7298d5397` |
| `SHP_1739068_15102026051415_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1739068_15102026051415_WEB.xml) | SUZLON 2026-09-30 (no pledge) | `aabe7121abaecc90effb207bff2b3959388eca82944cb80b00055246903ee0f5` |
| `SHP_1741974_19102026071903_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1741974_19102026071903_WEB.xml) | GMRAIRPORT 2026-09-30 (pledge 16.47%) | `d0d1b9a8bd3bcae6d656bc00c004d0bfc7ac780ccc88b1b4c3401ae2569f4854` |
| `SHP_1742991_21102026042504_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1742991_21102026042504_WEB.xml) | RELIANCE 2026-09-30 (DR custodian in NPNP) | `323f273fd5267a7c8c3558920b8756d8c54b828cc42f35fc6507561824031f9e` |
| `SHP_1737048_13102026050138_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1737048_13102026050138_WEB.xml) | ITC 2026-09-30 (no promoter, DR in NPNP) | `7c40d58e00a5597c7250602fcdc561e9fafb499ad5c86f7860ab641335aea0b8` |
| `SHP_1698632_21072026062045_WEB.xml` (https://nsearchives.nseindia.com/corporate/xbrl/SHP_1698632_21072026062045_WEB.xml) | JSWSTEEL 2026-06-30 | `d9a2f392f9221f2d1867f6fdd9ca4f6515f0f6213d1677b664afe9e648ea2b65` |

## Batch 9 Reg. 34 annual report XBRL (fetched 2026-11-13 via `api/annual-reports-xbrl` [A8], one file per request)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/AR_XBRL_TCS_09082026012216.xml` | B9: TCS FY26 consolidated. Screener parity FY26+FY25 comparative, PPE schedule, leases/ROU labels, PIT restatement test (X69-X76) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_TCS_09082026012216.xml` | `282d14593b060513d85d5c3f37d33bdf0c191e1ffe8f75a283f72ada09bf49cc` |
| `xbrl/AR_XBRL_TCS_14082025184751.xml` | B9: TCS FY25 consolidated. Cutoff (FY24 comparatives dropped), FY25-only NULL scores (C9, C23) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_TCS_14082025184751.xml` | `007169a3260f9d11f0df20b206e5083f04dd348151d32659e07057b6a58fae57` |
| `xbrl/AR_XBRL_ETERNAL_23092026175418.xml` | B9: Eternal FY26 consolidated. Screener parity FY26 + FY25, FX-in-investing divergence | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ETERNAL_23092026175418.xml` | `c7c45d85413ffdf238a4484f0d7a8823b8dfddcb4941d6d9601bf7adea80b880` |
| `annual/nse_annual-reports-xbrl_TCS_20261113.json` | B9: annual XBRL listing (symbol, type, broadcast time) | `https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=TCS` | `576b1db5338231ee1271b8df73318a674b56c5720271b5ed0c3ffaf4099c3bd0` |

Inspected for Batch 9 but not committed (3-8 MB each; registered in docs/tag_registry.yaml):

| File | Company / why | SHA-256 |
|---|---|---|
| `AR_XBRL_CUMMINSIND_04092026113506.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_CUMMINSIND_04092026113506.xml) | CUMMINSIND annual XBRL | `5c3a9f08d842b59162ac20d3a26d32e90934b1a8f9716c7164b00752a384da53` |
| `AR_XBRL_ITC_20082026185719.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ITC_20082026185719.xml) | ITC annual XBRL | `893b23f47cf1dbdec9be6aca849cf3493ea0ecb09d39d262dc0e6e59e04429ee` |
| `AR_XBRL_LT_04072026100144.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_LT_04072026100144.xml) | LT annual XBRL | `b32c686ccc3a43ee798c7502f8ec8b74bebba84b5deafc51136cb7d0d801942f` |
| `AR_XBRL_MARUTI_08102026183654.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_MARUTI_08102026183654.xml) | MARUTI annual XBRL | `d7c0ecdf8a97398572955150d5a7262b6b17f80533f9396b3e7e9103711dff11` |
| `AR_XBRL_NAUKRI_23092026174127.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_NAUKRI_23092026174127.xml) | NAUKRI annual XBRL | `d1a24dbdd7cfd3a310c3fe048119a4d40cdbd4ebb3dec0923bfbdc915923557a` |
| `AR_XBRL_RELIANCE_16072026204945.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_RELIANCE_16072026204945.xml) | RELIANCE annual XBRL | `2574f899e0385a6ed06e8244c0d20261672e653dbfed2a1e425e558b2fdfc22f` |
| `AR_XBRL_SRF_09082026022508.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_SRF_09082026022508.xml) | SRF annual XBRL | `9cd7592d33a6e62a4162ef662ad21c7e63c91133e406db78ea60e5a143965b98` |
| `AR_XBRL_SUNPHARMA_30102026194751.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_SUNPHARMA_30102026194751.xml) | SUNPHARMA annual XBRL | `2bc3400f673f83c4b721847fcf11146f1a92057b6cab7956c33b1b57801ee1e1` |
| `AR_XBRL_TATAPOWER_06082025142114.xml` (https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_TATAPOWER_06082025142114.xml) | TATAPOWER annual XBRL | `ff29b910b96886f8fb675b67ab6259793d2e433916d78810e595ad47861f8379` |

## Batch 10 Reg. 30 events and edge cases (fetched 2026-11-13; one file per request)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `events/ALTERATION_OF_CAPITAL_AND_FUND_RAISING_818_WebXMLFile_20261113_152039711.xml` | B10: ITC ESOP allotment (E6) | `https://nsearchives.nseindia.com/corporate/xbrl/ALTERATION_OF_CAPITAL_AND_FUND_RAISING_818_WebXMLFile_20261113_152039711.xml` | `9b72b0ed3608ad42276debcc6a1e8478565da5122f5a563f3e69e889a03de311` |
| `events/ANN_FRAUD_22342_WebXMLFile_20261113_211505185.xml` | B10: Shanthala fraud/default disclosure: no ISIN, text amount, SME (E7) | `https://nsearchives.nseindia.com/corporate/xbrl/ANN_FRAUD_22342_WebXMLFile_20261113_211505185.xml` | `39a39c2e7ad98f74434f4e86cde283aae92ab7aef96367eb84ca6665e5a60445` |
| `events/CIM_17080_WebXMLFile_20261113_201057828.xml` | B10: Shriram Properties: statutory auditor resignations (E5) | `https://nsearchives.nseindia.com/corporate/xbrl/CIM_17080_WebXMLFile_20261113_201057828.xml` | `71742e003ffb6a8841d6bf6a8a4b1078d5f54e0fdb18b947e8e2d3891dc8167d` |
| `events/CIM_19883_WebXMLFile_20261113_215018364.xml` | B10: CMS Info: KMP (company secretary) resignation (E5) | `https://nsearchives.nseindia.com/corporate/xbrl/CIM_19883_WebXMLFile_20261113_215018364.xml` | `358613fe16cdcf49a72328724f507651746ca664965c6c20ef808744e9a2f505` |
| `events/REG30_PARA_B_1254_WebXMLFile_20261113_183420254.xml` | B10: BEL order win, cumulative, amount INR (E3) | `https://nsearchives.nseindia.com/corporate/xbrl/REG30_PARA_B_1254_WebXMLFile_20261113_183420254.xml` | `bdbb6a4184922beaa76f5f7a06fdbcd0ddc93a7fcb5452a7a41633472f4abc60` |
| `events/REG30_PARA_B_2010_WebXMLFile_20261113_133459972.xml` | B10: Aptech order win (first of two byte-identical re-sends, E4) | `https://nsearchives.nseindia.com/corporate/xbrl/REG30_PARA_B_2010_WebXMLFile_20261113_133459972.xml` | `34eb9d686d6d7ab017c2bd2f1c2358de611ee045d80a7c80d1e6c204e0767c84` |
| `events/REG30_PARA_B_2010_WebXMLFile_20261113_133619258.xml` | B10: Aptech order win (second, byte-identical, E4) | `https://nsearchives.nseindia.com/corporate/xbrl/REG30_PARA_B_2010_WebXMLFile_20261113_133619258.xml` | `34eb9d686d6d7ab017c2bd2f1c2358de611ee045d80a7c80d1e6c204e0767c84` |
| `events/REG30_PARA_B_21978_WebXMLFile_20261113_182712819.xml` | B10: JSW Infra order win, named counterparty (E3) | `https://nsearchives.nseindia.com/corporate/xbrl/REG30_PARA_B_21978_WebXMLFile_20261113_182712819.xml` | `8ff50e31fb96bf03eea07e16fa8ab894801945c1bb68903732df4ae18184bb18` |
| `events/REG30_PARA_B_490_WebXMLFile_20261113_204423166.xml` | B10: Jindal Poly litigation update (E4) | `https://nsearchives.nseindia.com/corporate/xbrl/REG30_PARA_B_490_WebXMLFile_20261113_204423166.xml` | `95a69d45b2d045b5df3bf9e5f55a1b758a63c156ce83337a9f5c3b1e356f5044` |
| `events/nse_Online_announcements_20261113.xml` | E1: announcements RSS, 13-Nov-2026 21:52 IST (broadcast times) | `https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml` | `adfdfcee3c71d3eacdf0cc87b5c1fdc150c557264ec365fa494785392e4af330` |
| `xbrl/INTEGRATED_FILING_GI_1738196_14102026103636_WEB.xml` | B10: ICICI Lombard Q2 FY27 original of 1740432 (revision chain, E9) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_GI_1738196_14102026103636_WEB.xml` | `8b27eb7fec52e875a8eb79f384b0733b46e3d50d794849804ffa4dc81ea80205` |
| `xbrl/IF_INS_COM_IND_AS_21009_WebXMLFile_20261105_192422730.xml` | B10: Go Digit Q2 FY27 (byte-identical to the 12-Nov file: RESEND, E10) | `https://nsearchives.nseindia.com/corporate/xbrl/IF_INS_COM_IND_AS_21009_WebXMLFile_20261105_192422730.xml` | `b431634f9aae204ac71c8babc0e8ff93d3de3e7f0c3499384d347e28aafc1cb0` |

Inspected for Batch 10 but not committed: the other Reg. 30 files listed in docs/tag_registry.yaml (REG30_EVENT).

## Phase 1 audit evidence (fetched 2026-11-13 in this project's earlier runs, one file per request; committed later)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251017_F_0000.csv.zip` | Friday before a weekend: PrvsClsgPric chain across Sat/Sun (CAL3) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20251017_F_0000.csv.zip` | `8fa1328466662888d3a0c186809f0a9ed08418ce0ca2289eca3f839f8e6db670` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv.zip` | Monday after the weekend; session before the Muhurat day (CAL2, CAL3) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20251020_F_0000.csv.zip` | `6a42d7a22418104712706f2587c437de012e9aabd6a5b95874e8f52808d4ee3d` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251021_F_0000.csv.zip` | Diwali Laxmi Pujan 2025: Muhurat session bhavcopy, turnover ~20% of 20 Oct (CAL2) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20251021_F_0000.csv.zip` | `729f028f4dfde2d7dca1abca7b0277a87c4ca950dd0fd5d180ba8fc48c0b6456` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20251023_F_0000.csv.zip` | Session after the 22 Oct holiday: PrvsClsgPric = 21 Oct close for every security (CAL3) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20251023_F_0000.csv.zip` | `f06c74027d8b576d1b3ce7419bdb86472c153f7ac2ce687ed5dc949f2e00a105` |
| `discovery/nse_integrated-filing-results_equities_TCS_20261113.json` | Results discovery (A7): newest 20 Integrated Filing rows (Financials + Governance) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=TCS` | `2389cbc7d508c09eea436404e293862c96beb92ff902033c2ec24218fd6d6219` |
| `discovery/nse_integrated-filing-results_equities_TCS_page2_20261114.json` | A7 pagination (fetched 2026-11-14): `page=2` returns rows 21-22 of `totalCount` 22 (Mar 2025 standalone, Dec 2024 Governance); no overlap with page 1 | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=TCS&page=2` | `38bb3a80b3052f51e813ad73588c537f74dea5e4996054e52be7a90639b54a89` |
| `discovery/nse_integrated-filing-results_equities_ADANIGREEN_20261114.json` | A7: 10 of 20 rows have `broadcast_Date: null` (totalCount 36: two pages) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=ADANIGREEN` | `128f7abe359a2ece747b37a36c2245c808b82b255ddfc6747e059d86a2ae65e9` |
| `discovery/nse_integrated-filing-results_equities_COALINDIA_20261115.json` | A7 / A13 (fetched 2026-11-15): every `xbrl`, `ixbrl` and `pdf_attach` link is on `nsearchives.nseindia.in` (was .com); the files are byte-identical to the .com host | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=COALINDIA` | `b188ee32413786f5fccab423d1ab838b07829dd7e4b0db83ce21bbf05448763e` |

## Live-backfill parser regressions (fetched 2026-11-14)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/AR_XBRL_SPARC_08092026160440.xml` | X77: `NumberOfShareholdersOfCompany` filed under an INR unit with sub-paise digits (1.42865); the whole annual filing failed to stage | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_SPARC_08092026160440.xml` | `afce2599db7364ffa7c1609ca539b5bc1a8be2c764ec7ddc062dccbb05c9badc` |

## Index closes and equity master (fetched 2026-11-14, one request each)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `indices/ind_close_all_13112026.csv` | IDX9: daily index closes (167 indices) | `https://nsearchives.nseindia.com/content/indices/ind_close_all_13112026.csv` | `5aa75542683abc5c13c7906bc14f81639cb80a9eff31a1cf78b9af4028485dbf` |
| `indices/nse_EQUITY_L_20261114.csv` | IDX10: NSE equity master (2,635 listings) | `https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv` | `c78517837fe47a29a2b4cbb970899c202eb45fab827134aacf8287835ec5acee` |

## ETF unit splits and re-ISINs (live backfill 2026-11-14)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20260226_F_0000.csv.zip` | Day before five Kotak ETF unit splits (CA13) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260226_F_0000.csv.zip` | `8ef7902a0ae594af7e432d4beb72050e2ae712a7fac5638849f61b71822d06b5` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20260227_F_0000.csv.zip` | BANKNIFTY1, CONS, MIDCAP, NV20, SILVER1 re-ISIN at ~1/10 (CA13) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20260227_F_0000.csv.zip` | `64d4c291413416453c97a00196d8f18f772a1daac58328a76a99145137ff710b` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250227_F_0000.csv.zip` | Day before HDFCLIQUID re-ISIN (CA13) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20250227_F_0000.csv.zip` | `e0f8d2b6eb79a24e66e2560210357410b129465f8346ae039f979539c7cd7b01` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20250228_F_0000.csv.zip` | HDFCLIQUID new ISIN, no price effect (CA13) | `https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20250228_F_0000.csv.zip` | `9b32219ea32ccac0952c6d54cbfdd9b89c2f0d552cb6be2bc76103585ff18235` |

## Corporate-action purpose texts (live backfill 2026-11-14; 30-day API windows, one request each)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `corp_actions/nse_corporateActions_equities_21-09-2026_20-10-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=21-09-2026&to_date=20-10-2026` | `f8f4f3579e96ded9f28f619cbfb77244e46a924db2114ffbea0a3de5c2f31a1e` |
| `corp_actions/nse_corporateActions_equities_21-10-2026_19-11-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=21-10-2026&to_date=19-11-2026` | `bae33f29505b1a10dd0b491f6987ca8e7fdf88d8398fc57a0facffb6b51f25f4` |
| `corp_actions/nse_corporateActions_equities_22-08-2026_20-09-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=22-08-2026&to_date=20-09-2026` | `ab35203e01caec033676887db0fd9e6358a34c6e39d6f7158adf33b4742dabe7` |
| `corp_actions/nse_corporateActions_equities_23-06-2026_22-07-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=23-06-2026&to_date=22-07-2026` | `341aa441c2292249c5a92e6e9b8eed79bda1c1fe5115217edebbfaaf5a261b82` |
| `corp_actions/nse_corporateActions_equities_23-07-2026_21-08-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=23-07-2026&to_date=21-08-2026` | `2dba3824033c0324975ecd1e10a332d840ba9d812d379843ba588ba3d28f3a92` |
| `corp_actions/nse_corporateActions_equities_24-01-2026_22-02-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=24-01-2026&to_date=22-02-2026` | `bac1d9afae78501d55ad8a07b16767af36acda30acf72124d9ce2fd22e6aadb1` |
| `corp_actions/nse_corporateActions_equities_24-05-2026_22-06-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=24-05-2026&to_date=22-06-2026` | `11a6c4ba6b16503209bd00912ef35ea4f0acd80e757a9f44a5b5de949789f7bc` |
| `corp_actions/nse_corporateActions_equities_25-12-2025_23-01-2026.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=25-12-2025&to_date=23-01-2026` | `ceb70d045bf0d709819d2032a8e1b7e8de531a2046b0cd114cf63af52ed5242c` |
| `corp_actions/nse_corporateActions_equities_28-02-2025_29-03-2025.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=28-02-2025&to_date=29-03-2025` | `fbdc850c8c083165b85537f11014c14213490a37f39b6b12404e61de98ba0f30` |
| `corp_actions/nse_corporateActions_equities_28-06-2025_27-07-2025.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=28-06-2025&to_date=27-07-2025` | `8853a662470df666e2f43ee020a1990c1fa80171a2ba38fffa94eff9df7a8b25` |
| `corp_actions/nse_corporateActions_equities_29-01-2025_27-02-2025.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=29-01-2025&to_date=27-02-2025` | `01797503a034eb972c7f3dbf79af0e24fafca416270572480516fe19aef7f188` |
| `corp_actions/nse_corporateActions_equities_29-05-2025_27-06-2025.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=29-05-2025&to_date=27-06-2025` | `9bebeaead788d108d4da9b079c30865143d8576810dbcc77a6ae1aac09f6e8d2` |
| `corp_actions/nse_corporateActions_equities_30-12-2024_28-01-2025.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=30-12-2024&to_date=28-01-2025` | `3be4f001d7c6bc52dfd76d67c4a0845628295902aac78038580b75f2e2fc34a8` |
| `corp_actions/nse_corporateActions_equities_31-10-2024_29-11-2024.json` | Live backfill 2026-11-14: real purpose texts for the CA11 rules (AGM/EGM, dividend combinations, typos, rights, consolidation) | `https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date=31-10-2024&to_date=29-11-2024` | `14e8a44caf65f07112e64d179da25cb1c8b80f3adeec588a58608eef5844493d` |

## Segment and geography tables (copied 2026-11-14 from the local vault blob, gunzipped, sha256 verified)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/AR_XBRL_SRF_09082026022508.xml` | X97-X99: SRF FY26 consolidated Reg. 34 annual (fetched 2026-11-14T04:35:26Z; inspected for Batch 9, now committed). Business segments with `UnallocatedAmountsMember`, `EliminationOfIntersegmentAmountsMember` and `MaterialReconcilingItemsMember`; geography with country labels on `GeographicalAreasAxis` | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_SRF_09082026022508.xml` | `9cd7592d33a6e62a4162ef662ad21c7e63c91133e406db78ea60e5a143965b98` |

## Disclosure facts (copied 2026-11-16 from the local vault blob, gunzipped, sha256 verified)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/AR_XBRL_ELECON_23072026161247.xml` | X116 / X117: ELECON FY26 standalone Reg. 34 annual (fetched 2026-11-14T03:38:21Z). Non-zero `TradeReceivablesDueByDirectors` (442.1 Mn) next to `TradeReceivablesDueByOthers`; `TradeReceivablesDueByDirectorsOtherOfficersOrOthers` = their sum = total trade receivables (a subtotal that includes third parties) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ELECON_23072026161247.xml` | `50a8e66e066fb65d7da92939a486593b6cb0f8331c2fc63b47ad17d949509dc7` |
| `xbrl/AR_XBRL_INOXINDIA_09082026015537.xml` | X117: INOXINDIA FY26 consolidated Reg. 34 annual (fetched 2026-11-14T04:00:50Z). FY25 comparative: `TradeReceivablesDueByPrivateCompaniesInWhichAnyDirectorIsDirector` = `TradeReceivablesDueByFirmsOrCompaniesInWhichAnyDirectorIsPartnerOrDirector` = 528.618 Mn (the firms / companies subtotal); FY26: 0 | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_INOXINDIA_09082026015537.xml` | `6890f120eaec7192946dc97b938960df7ab9a088635bee641bf72177e9eee51a` |
| `xbrl/SHP_1752549_04112026032917_WEB.xml` | X118: SAMMAANCAP Reg. 31 as of 2026-10-30 (fetched 2026-11-14T04:31:32Z). Declares warrants, convertible securities, partly paid-up shares, DVR shares, locked-in shares and ESOPs `true` (every other committed SHP fixture files the first four `false`) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1752549_04112026032917_WEB.xml` | `7248bfdf1dc49ff4382782829ea12190a43bbacbe95cf2623147c4827a70ec68` |

## Audit opinions (copied 2026-11-17 from the local vault blob, sha256 verified)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/AR_XBRL_TITAGARH_13012026105336.xml` | X121 QUALIFIED: TITAGARH FY25 standalone Reg. 34 annual. "Qualified Opinion" / "Basis for Qualified Opinion" headings; checkbox `true` (fetched 2026-11-14T04:41:27Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_TITAGARH_13012026105336.xml` | `8ecfed49a39add40599695b820e483b7970599747907b5379c98e670a7986e5f` |
| `xbrl/AR_XBRL_RKFORGE_24102025122553.xml` | X121 / X123 QUALIFIED + conflict: RKFORGE FY25 consolidated. "Qualified Opinion" headings and an Emphasis of Matter section while `WhetherAuditorsReportHasBeenQualified...` is `false` (fetched 2026-11-14T04:30:00Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_RKFORGE_24102025122553.xml` | `d3544d6605eda2c0b66bb8fdbe1a9f3cd3678fec4964b7bacc60138bdbb0762d` |
| `xbrl/AR_XBRL_VARROC_02092026142002.xml` | X121 / X123 QUALIFIED + conflict: VARROC FY26 consolidated. Qualified opinion in the text, checkbox `false` (fetched 2026-11-14T04:45:56Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_VARROC_02092026142002.xml` | `58197f59581c5121e6d8f8381499234052b7c836c80bccf7aa6c76f5535e2982` |
| `xbrl/AR_XBRL_RELINFRA_18092026172005.xml` | X121 / X123 DISCLAIMER + conflict: RELINFRA FY26 standalone. "Disclaimer of Opinion" headings, checkbox `false` (fetched 2026-11-14T04:29:30Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_RELINFRA_18092026172005.xml` | `b757ad5fe5908749c1390d0a4e9dcf1df5d7ff0321ebe12a1208cb1940b33915` |
| `xbrl/AR_XBRL_RELINFRA_06092025221939.xml` | X121 DISCLAIMER: RELINFRA FY25 standalone. "Disclaimer of Opinion" headings, checkbox `true` (fetched 2026-11-14T04:29:46Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_RELINFRA_06092025221939.xml` | `862fff65a653e95ed20763e6ed2e57194e93853e05603ce03e01234ccadc54a1` |
| `xbrl/AR_XBRL_MMTC_11022026110533.xml` | X122 going concern: MMTC FY25 consolidated. "1. Material Uncertainty Related to Going Concern" (enumerated) under the Emphasis of Matters heading; unmodified opinion, checkbox `true` (fetched 2026-11-14T04:16:27Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_MMTC_11022026110533.xml` | `6e19b0c8e7fb3456f01a35681221292f299d9eca7a24470cd3aabac045ac95b3` |
| `xbrl/AR_XBRL_IDEA_19092025180318.xml` | X122 going concern: IDEA FY25 consolidated. "Material Uncertainty Related to Going Concern" section on the group's financial condition; unmodified opinion (fetched 2026-11-14T03:57:47Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_IDEA_19092025180318.xml` | `b80d6b2f0dde5e5e51f348e925d128945306f232b90dde43be7516f1b2b3344f` |
| `xbrl/AR_XBRL_RPOWER_06092025221905.xml` | X122 GOING_CONCERN_COMPONENT: RPOWER FY25 consolidated. The section's only paragraph reports that the auditors of a subsidiary (RSTEPL) highlighted a material uncertainty (fetched 2026-11-14T04:30:20Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_RPOWER_06092025221905.xml` | `518d7f65d3869766112eb03c7453755b31d9270b7d5449755e0a500e0ec1662e` |
| `xbrl/AR_XBRL_CONCOR_11022026153323.xml` | X122 GOING_CONCERN_COMPONENT: CONCOR FY25 consolidated. The section sits under the entity sub-heading "3. CONCOR AIR LIMITED" (a subsidiary) inside the Emphasis of Matter list (fetched 2026-11-14T03:33:30Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_CONCOR_11022026153323.xml` | `aea1392659ef6445973ea24023ed11f8dd6e6f703519c19675ad909d4912fe76` |
| `xbrl/AR_XBRL_JPPOWER_13012026113224.xml` | X121 QUALIFIED + X122 GOING_CONCERN_COMPONENT: JPPOWER FY25 consolidated. Qualified opinion; the heading "Material Uncertainty related to the going concern - of Subsidiary Companies" names the components (fetched 2026-11-14T04:04:57Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_JPPOWER_13012026113224.xml` | `830dd126fe8c0899db4af900aad78cd9a3494ce4bf314ec8dce08a65365b92a5` |
| `xbrl/AR_XBRL_BEML_13012026164812.xml` | X121 / X122 emphasis of matter: BEML FY25 consolidated (revised report). "Opinion" and "Emphasis of Matter" headings; the legal-requirements section after the body still says "Except for the effects of the matter described in the Basis for Qualified Opinion section" (not read); checkbox `true` (fetched 2026-11-14T03:24:18Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_BEML_13012026164812.xml` | `75dd6038b5a1dd06111d4fec125593381c8581fc75f9dff46dfb8711610367fe` |
| `xbrl/AR_XBRL_MFSL_17102025125715.xml` | X122 emphasis of matter: MFSL FY25 standalone. Unmodified opinion with an Emphasis of Matter section (fetched 2026-11-14T04:15:16Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_MFSL_17102025125715.xml` | `c844ce5f7452b16a54997b47b7122e797f4cc143ffa6b0f30348368eacdbd86b` |
| `xbrl/AR_XBRL_SWANCORP_13012026103454.xml` | X121 OPINION_PARAGRAPH: SWANCORP FY25 standalone. The whole report is one block without line breaks (no heading line); unmodified opinion paragraph (fetched 2026-11-14T04:37:11Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_SWANCORP_13012026103454.xml` | `bc9d9be6b18e9a4fb0d1c1240feff0633aabe802c20a7cccbd74b70e7392bf86` |
| `xbrl/AR_XBRL_SUNTV_13012026154758.xml` | X121 NO_REPORT: SUNTV FY25 consolidated. `DisclosureInAuditorsReportExplanatory` = "As per Attachment" (fetched 2026-11-14T04:36:19Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_SUNTV_13012026154758.xml` | `11773eef9c939993eb136374450e1da2257140a0ce29cd8c54af56889452b858` |
| `xbrl/AR_XBRL_MTARTECH_13012026142914.xml` | X121 NO_REPORT: MTARTECH FY25 consolidated. The element holds only the CARO annexure ("Annexure '1' referred to in paragraph ...") (fetched 2026-11-14T04:17:19Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_MTARTECH_13012026142914.xml` | `e00b89964e8dc94c848a322b807249556f5a5de69ab3b1739f23d00be969b959` |
| `xbrl/AR_XBRL_VENTIVE_23092025192320.xml` | X121 / X123: VENTIVE FY25 standalone. Unmodified opinion on the financial statements; the internal-financial-controls annexure has a "Qualified Opinion" heading (not read); checkbox `true` (fetched 2026-11-14T04:47:00Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_VENTIVE_23092025192320.xml` | `20c2a4a11fa36d87cd543720629e5d26ae6c0a965e05fdf8f27133fab8fc66e2` |
| `xbrl/AR_XBRL_OIL_17102025191837.xml` | X121 / X122: OIL FY25 consolidated. A subsidiary auditor's "Disclaimer of Opinion" and "Material Uncertainty relating to Going Concern" headings quoted in the group report (opening quotation marks): unmodified, no going-concern section of its own (fetched 2026-11-14T04:21:33Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_OIL_17102025191837.xml` | `3a249605f8e9d3d48afd2048e9435858765ba91f47566aad732b767bcc7a20ed` |
| `xbrl/INTEGRATED_FILING_INDAS_1707551_04082026041230_WEB.xml` | X124 results QUALIFIED: EMAMI Q1 FY27 consolidated Integrated Filing. Statement on impact of audit qualification, `OpinionOfAuditors` / `TypeOfAuditQualification` "Qualified opinion" (a limited-review quarter) (fetched 2026-11-14T03:38:09Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1707551_04082026041230_WEB.xml` | `b6d1dffeef1eca50ede5eac2de1ce2ee4d23fee4ede5bedc9c39e1131032ad04` |
| `xbrl/INTEGRATED_FILING_INDAS_1461904_01062025070430_WEB.xml` | X124 results QUALIFIED: RKFORGE Q4 FY25 consolidated. One `AuditQualificationAxis` member, "Qualified opinion", "Whether appeared first time" (fetched 2026-11-14T04:29:48Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1461904_01062025070430_WEB.xml` | `384f7c108564b7a32cdc80ebb8652adb1635ef88308879380d2380ad68525b57` |
| `xbrl/INTEGRATED_FILING_INDAS_1461165_30052025115826_WEB.xml` | X124 results QUALIFIED: TITAGARH Q4 FY25 consolidated. `OpinionOfAuditors` "Qualified opinion" without any `TypeOfAuditQualification` fact (fetched 2026-11-14T04:41:20Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1461165_30052025115826_WEB.xml` | `3279638447f39a9d8a4d8f43da67fde3e9804b8919df23f28a58e8276500c646` |
| `xbrl/INTEGRATED_FILING_INDAS_1758732_14112026091104_WEB.xml` | X124 results DISCLAIMER: ASHOKLEY Q2 FY27 consolidated. `OpinionOfAuditors` / type "Disclaimer of opinion" (fetched 2026-11-15T04:48:56Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1758732_14112026091104_WEB.xml` | `7fbef8eed0143862320faf3418ca67b2c6bbaac1d5ae3f072f84e24c0099184b` |
| `xbrl/INTEGRATED_FILING_INDAS_1449896_24052025124314_WEB.xml` | X124 results DISCLAIMER: RELINFRA Q4 FY25 consolidated. Two disclaimer qualifications, "Repetitive" (fetched 2026-11-14T04:29:17Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1449896_24052025124314_WEB.xml` | `9f4012ed1483c48c8f9ff19a6485067d35052fbd6ece1e6522fe714cf672ce59` |
| `xbrl/INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml` | X124 results DISCLAIMER: RELINFRA Q4 FY26 consolidated. Three qualifications (two disclaimers, one qualified); `OpinionOfAuditors` "Disclaimer of opinion" (fetched 2026-11-14T04:29:03Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1672152_23052026112720_WEB.xml` | `034f29ecb3a2b64601c4ab73e997ab2dc50afe9f2fdf99fcb30bb96574ca3bb4` |

## Reg. 23(9) disclosure period (copied 2026-11-17 from the local vault blob, gunzipped, sha256 verified; SEBI circular fetched 2026-11-17)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `rpt_half_year/INTEGRATED_FILING_INDAS_1569348_08112025095047_WEB.xml` | X160: POLYMED Q2 FY26 standalone Integrated Filing, Reg. 23(9) rows on the Jul-Sep context (fetched 2026-11-14T04:25:10Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1569348_08112025095047_WEB.xml` | `a1af1006aa32b970376b2fda6173e8b5f8547dfe5a564675a8749eff35839998` |
| `rpt_half_year/INTEGRATED_FILING_INDAS_1672831_25052026105506_WEB.xml` | X160: POLYMED Q4 FY26 standalone, Jan-Mar context; Q2 + Q4 amounts = the FY26 Ind AS 24 schedule, Q4 opening = Q2 closing (fetched 2026-11-14T04:25:06Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1672831_25052026105506_WEB.xml` | `fc19a4137d3540c71b38e5d580a8661c5f975845cb7c6b46510d06f6fc1b4be1` |
| `rpt_half_year/AR_XBRL_POLYMED_03102026150104.xml` | X160: POLYMED FY26 standalone Reg. 34 annual (Ind AS 24 schedule, Lakhs) (fetched 2026-11-14T04:25:23Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_POLYMED_03102026150104.xml` | `016bb4831450ac91ae7a135606b7033a7d0b774acb85e206b8cc0a257a248104` |
| `rpt_half_year/INTEGRATED_FILING_INDAS_1503459_05082025091749_WEB.xml` | X160: CASTROLIND (calendar financial year) Q2 FY25 standalone Integrated Filing, Apr-Jun context (fetched 2026-11-14T03:28:13Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1503459_05082025091749_WEB.xml` | `938f3f4cb2200078896db19cffd8db4294b642a9e8edc5f2a6c23cf252253155` |
| `rpt_half_year/INTEGRATED_FILING_INDAS_1617588_03022026083116_WEB.xml` | X160: CASTROLIND Q4 (Oct-Dec 2025 context) standalone; Jun + Dec amounts = the calendar-2025 Ind AS 24 schedule (fetched 2026-11-14T03:28:11Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1617588_03022026083116_WEB.xml` | `0d4239f7a81d5288a4c905787c70fa2461f4aa01203ba068afbf658fdfcd782a` |
| `rpt_half_year/AR_XBRL_CASTROLIND_28042026134722.xml` | X160: CASTROLIND year to 2025-12-31 standalone Reg. 34 annual (Crores) (fetched 2026-11-14T03:28:27Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_CASTROLIND_28042026134722.xml` | `68f9137bb5bb74a8fd5dc5710bf922bf02bbb9f5ce4ebaa993f7090f538f73af` |
| `rpt_half_year/INTEGRATED_FILING_INDAS_1453034_27052025055732_WEB.xml` | X161: EIDPARRY Q4 FY25 standalone Integrated Filing (closing balances at 2025-03-31) (fetched 2026-11-14T03:37:43Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1453034_27052025055732_WEB.xml` | `83843265468722be3b617f6d443b6c1c383016cf68df044d32aa51ad2c0de768` |
| `rpt_half_year/INTEGRATED_FILING_INDAS_1571468_11112025064700_WEB.xml` | X161: EIDPARRY Q2 FY26 standalone Integrated Filing (fetched 2026-11-14T03:37:37Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1571468_11112025064700_WEB.xml` | `62e4e8fe8a3aa1e823149ca0518115a6d21c39fb6e2127017055092e6ac80bfd` |
| `rpt_half_year/INTEGRATED_FILING_INDAS_1673448_26052026074140_WEB.xml` | X161: EIDPARRY Q4 FY26 standalone, Jan-Mar context: amounts are the whole FY26 and the opening balances are those of 2025-03-31 (fetched 2026-11-14T03:37:29Z) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1673448_26052026074140_WEB.xml` | `5a8c10e43e5946c81a58263b0028d8c8abe9a7ac2b7c62db957c26a4c827cf8f` |
| `rpt_half_year/AR_XBRL_EIDPARRY_07092026144251.xml` | X161: EIDPARRY FY26 standalone Reg. 34 annual (Ind AS 24 schedule, Lakhs) (fetched 2026-11-14T03:37:47Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_EIDPARRY_07092026144251.xml` | `45874b420acf09033d58cd34feacaf330cef4d1c172503c7e06c810b8940b8af` |
| `circulars/sebi_cir_2024_185.pdf` | X160: SEBI circular SEBI/HO/CFD/CFD-PoD-2/CIR/P/2024/185 (31 Dec 2024), Annexure 1 Integrated Filing (Financial) format D (Reg. 23(9) related-party transactions), notes 1 and 4; NSE copy saved as `NEW SEBI_0.pdf`, renamed only (fetched 2026-11-17) | `https://nsearchives.nseindia.com/web/sites/default/files/inline-files/NEW%20SEBI_0.pdf` | `e23830379fdeb1557ea3afa9a3f60d5b0f11bf48dcb619a649190db4bd5cb6a1` |
| `circulars/sebi_cir_2024_185.txt` | DERIVED: `pdftotext -layout circulars/sebi_cir_2024_185.pdf` (poppler 24.02) | `3720faec1b5e7607dab41315063765bc03b833c94b2b22eb1928b69f58e54b66` |

## Quarantine rules X150-X155 (copied 2026-11-17 from the local vault blob, gunzipped, sha256 verified)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl/AR_XBRL_CHOICEIN_28102025170241.xml` | X150 ACTUAL_ROUNDING_IS_RUPEES: Choice International FY25 standalone Reg. 34 annual, `LevelOfRoundingUsedInFinancialStatements` = Actual (fetched 2026-11-14T03:31:30Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_CHOICEIN_28102025170241.xml` | `30a97af5994b4df7871f4b2542cf217cfaeefdf4d82b0e69c41d5a2e852bd548` |
| `xbrl/AR_XBRL_ALOKINDS_14082026191942.xml` | X151 UNDECLARED_PRE_CUTOFF_CONTEXT: Alok Industries FY26 consolidated; IncomeTaxesPaidRefund in undeclared `D2024` (fetched 2026-11-14T03:07:07Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ALOKINDS_14082026191942.xml` | `777947d020faa78dcebeac4da8d5cd7090ddaba7d746306e3b2d3262d02a7134` |
| `xbrl/AR_XBRL_ENRIN_13032026115920.xml` | X152 IRREGULAR_COMPARATIVE_STUB: Siemens Energy India FY25 (Oct-Sep) standalone; comparative 2024-02-07..2024-09-30 (fetched 2026-11-14T03:39:22Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ENRIN_13032026115920.xml` | `90af8b194308d17a8ac14e7b9bb0b317cb190f5c9f0b1b27804c277b7f9469b0` |
| `xbrl/AR_XBRL_ABLBL_01122025184209.xml` | X152 negative case: Aditya Birla Lifestyle Brands FY25 standalone; only period 2024-04-09..2025-03-31, stays IRREGULAR_PERIOD (fetched 2026-11-14T03:03:35Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_ABLBL_01122025184209.xml` | `4979ff0bd5c9600635b033ea77ac3c5d4fb69dc099d150072c374fe2b4536df0` |
| `xbrl/AR_XBRL_PREMIERENE_28012026112034.xml` | X153 EP_EXPENDITURE_FACE_LINE: Premier Energies FY25 standalone; EXPENSE_COMPONENTS gap 622,640,000 = the filed E&P expenditure element (fetched 2026-11-14T04:26:19Z) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_PREMIERENE_28012026112034.xml` | `23800016ae75a17076fa72136d9ffdae06178d23e88c299a88930958d7570d72` |
| `xbrl/SHP_1652898_17042026122104_WEB.xml` | X154 SHP_EXCHANGE_SPECIFIC_TAXONOMY: BSE Ltd Reg. 31 as of 2026-03-31 on `SHP_Exchange_Specific/2025-10-31` (fetched 2026-11-14T03:27:49Z) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1652898_17042026122104_WEB.xml` | `faca330e11042cff491ab53028b94bf153ccbb4fb602b058cdcc47d43110f4db` |
| `xbrl/SHP_13769_15072025060551_WEB.xml` | X154: BSE Ltd Reg. 31 as of 2025-06-30 on `SHP_Exchange_Specific/2025-05-31`; trading members as non-promoter non-public, percent points (fetched 2026-11-14T03:27:53Z) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_13769_15072025060551_WEB.xml` | `3432d6cebd98de02466ceb5285c0a6799c2d630dcce9569132bf7a18f4442a4c` |
| `xbrl/IF_INS_COM_IND_AS_19757_WebXMLFile_20261104_181240292.xml` | X155: Niva Bupa Q2 FY27 standalone Ind AS insurance Integrated Filing; `OtherAdjustments` inside insurance service expenses (fetched 2026-11-14T04:18:59Z) | `https://nsearchives.nseindia.com/corporate/xbrl/IF_INS_COM_IND_AS_19757_WebXMLFile_20261104_181240292.xml` | `3d75086dedbdd71d8365adf2f4be51faffd02b319ef56d9b8195ea01fab79405` |
| `xbrl/SHP_1697747_21072026110424_WEB.xml` | X156: KIMS Reg. 31 as of 2026-06-30 stating ISIN INE007C01025 (KIMS is INE967H01025); resolved by the X88 name test once the SHP parser passes NameOfTheCompany (fetched 2026-11-14T04:08:24Z) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1697747_21072026110424_WEB.xml` | `9811034d0a377dc5dbe4c0c8ee88b4e9fa13a78502d1a4acf132e265be346aa8` |
| `xbrl/INTEGRATED_FILING_INDAS_1502813_05082025045022_WEB.xml` | X171 SC0: United Polyfab Gujarat (UNITEDPOLY, INE368U01029) Integrated Filing with `ScripCode` 000000 (fetched 2026-11-17T07:07:23Z on a runner) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1502813_05082025045022_WEB.xml` | `45d2ed8f8f97ef37a4d222e9d540392b6eaa284da8dc164573b12e9b2c2407f2` |
## QA X180-X182 annual checks (copied 2026-11-17 from the local vault blob, gunzipped, sha256 verified)

Kept in `annual_checks/`, outside `xbrl/`, so the end-to-end fixture market and its pinned counts do not see them.
Read by `tests/test_x180_annual_checks.py` (X181).

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `annual_checks/INTEGRATED_FILING_INDAS_1426806_28042025073334_WEB.xml` | X181: GREENPLY Q4 FY25 standalone results. `FaceValueOfEquityShareCapital` 10 with paid-up 124,873,000: paid-up / face = 12,487,300 shares, 10x off | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1426806_28042025073334_WEB.xml` | `d69085d72a03656b59eb2c47b85406fb610a5e9786acd961a00f2511a8e023cc` |
| `annual_checks/AR_XBRL_GREENPLY_24092025103040.xml` | X181: GREENPLY FY25 standalone Reg. 34 annual. `NumberOfSharesPaidUp` 124,873,295 at 31-Mar-2025 | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_GREENPLY_24092025103040.xml` | `b65488a3f0f05e6ea9b6c0b92e0380245cf9c664d677c3df3bf1d99c1524230a` |
| `annual_checks/SHP_198395_1419898_19042025033622_WEB.xml` | X181: GREENPLY Reg. 31 shareholding as of 31-Mar-2025, total 124,873,295 shares (= the annual count) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_198395_1419898_19042025033622_WEB.xml` | `dc519708ed76e862ea9b0ae21a992fd49209237b4914a0811448ffb2c2d163b9` |
## Ratio rules, NEW members (QR; copied 2026-11-17 from the local vault blob, gunzipped, sha256 verified)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `ratio_rules/INTEGRATED_FILING_INDAS_1649412_11042026052716_WEB.xml` | X194: AQYLON (formerly SABTNL) Q4 FY26 standalone Integrated Filing. Capital employed at 31-Mar-2026 = 25.37 − 31.05 + 4.24 + 13.81 = 12.37 Cr; FY26 PBT 7.42 Cr, finance costs 2.80 Cr | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1649412_11042026052716_WEB.xml` | `2605d730644e9612b99c0c20e7ab6ae4d55595f2fccd46240d7ced8f3f9264fd` |
| `ratio_rules/INTEGRATED_FILING_INDAS_1454104_28052025103044_WEB.xml` | X194: the same company's Q4 FY25 standalone filing: capital employed at 31-Mar-2025 = 25.37 − 36.81 + 0 + 0 = −11.44 Cr (both borrowings lines filed as nil) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1454104_28052025103044_WEB.xml` | `97e6d65028f35ffb7aa75254052627af746234c67848189a16f1afdce29d791b` |

## Screener goldens (local only, not committed)

The repository is public, so the user-supplied Screener Excel exports (2026-11-13; 42 distinct files, some uploaded twice)
and their extracted Data Sheets are **not** committed. Re-create them with
`python scripts/extract_screener_golden.py EXPORT.xlsx ... --out data/screener_golden` (`data/` is gitignored). The
parity harness carries only the specific figures it asserts. Hashes:

| Export sha256 | Extracted JSON sha256 | File |
|---|---|---|
| `9f876141bbb6c9eaacf87b6b7fdcdf73e15a7027e5fb210d0f02b38a9441b986` | `218960af70b9ac0eaf4a1719dd020106c79e8fad21a089b9a3b62270bbf2f953` | `AIA_Engineering.json` |
| `3eff9d1b9122afe189c0b75a2416ef1f9b91cb3bd90b12d39dd2abb37677722f` | `947e95fd42f4b0b97f4810f3af720dcf321573c7bca740fe48c25a1f8604e71d` | `APL_Apollo_Tubes.json` |
| `05b25df6981044b0d7fb556aac4f68c77da1b62247e74d6bbe18f59fd9dedbda` | `4eaad51e02e1657170df89a820ca49af1950668274bdaacff23236e57d366ae1` | `Bajaj_Finance_1.json` |
| `900eda586df60fedc895b3336081a597a387673a479f499dd28dea06be986ce6` | `31d7c70760658e97553e83273f288389180ed56ef32c783694cd61524bc6605e` | `Bajaj_Finance_2.json` |
| `3298a53759b988a442fc3f876f215e592b55ce66484fbd7817ebb0d9141c19ac` | `4503c96403ee248da64372739b9078c6db41346b72bbc618650dfccab6f3fe69` | `Cholaman_Inv_Fn.json` |
| `2a8181ec598b0f113d96f6ce911b14ce98a4ec9c787d85ce817f7ba8bbc7392a` | `687d82317b0ac359ecfc7f4b1d39d172d0e9d4c1684ac6156d7f87d2edb973f5` | `Cummins_India.json` |
| `8759231e253cdd15b056e3d4d0ce91eedc07acbc491845e554daa17d3b62f409` | `649ecb2dda5cd142c6f2a41529507b4c7c1e7d430fb87857068a3fb6e900b4b9` | `Delhivery.json` |
| `08a48ee253914da355241b8022a7cc8db98a3725f4339575862421d1dc19182b` | `b5c833ba3a63f737a14a867c930b6985604de88e07db53456116ae05f4ec3d2e` | `Elin_Electronics.json` |
| `dfecc6734e311f2304969d516169e203be11d83b70358774478ce8627189a40f` | `9e93caa38f3ff3133059544bfde31374cb882048cbf7216d48878549a6fecdb8` | `Elin_Electronics_1.json` |
| `a3987966d0824c6b96439e0daefe75d114d9947fd12750082268763d8824bc21` | `97c07878e56b14d32d210016c30892684196c5aa949c397b64ec1184dafbf839` | `Eternal.json` |
| `36f05105f05d15a994dde21de2595fbde778dffecbe5d322c69032ee209c4a05` | `060bb987c7e50325e58bf0eac36bcefb8136f98aca3138d46692b804e3821ef1` | `FSN_E_Commerce.json` |
| `e047fb373a15866a2e5541228275c2142c5f2c42046d7094fe953f1ec49f8230` | `2e36ebf3a8eabefd54f3852240e09a0972cbf26d36ad02960f8a9dcc39026597` | `HDFC_Bank_1.json` |
| `6a08a43037234a7db10ac8b9ab50d6b8d44b1e63b3cdeb711f09bfcf0e9389d2` | `dd165ddb04cbff08569dba0ae32979dc202928cbff0b9da082c959d2d7b0e1fe` | `HDFC_Bank_2.json` |
| `67d37e45fa0c5daf478f4a868ac7055df8303e0d1906bd9c79eae458f1c8a829` | `e2737a83e14713ac99ffef3e08d6ce56e7aaa015ba4ebfad6bc65c1e63e7cf12` | `HDFC_Life_Insur.json` |
| `30f81d594b343e2a295d39530680d7abb619d94a4217680a784ea63b4d148335` | `0c8360fa1de536885cacbc34ab699611f72f937ef65d5f61737bfa29cd22b4e9` | `ICICI_Lombard.json` |
| `99ef74f02f51cc2c40218d824b9dfc6a668e836e931364a70b4a46a4a0d8ca79` | `bac1d0d7702d34e1d6af37f3ef181a0c60f29defb802c9304dfefdebfb596bc5` | `ITC_1_1.json` |
| `bdb7a4bd9da67e0769765a989cac0f3eb5f66fb23af5b3dbcea0302a938ef765` | `4106892d90dec9f5dfb4d9259e5f3a7016a4c0882e50b4deadd79adcbfc311db` | `ITC_1_2.json` |
| `ccc560c4c6ef4c89058d68bf9ec5807c566ece52135da84910ce6a1e574eb0cd` | `23d62376ced6348ccae63f94554ceefbe0126a250d4692ba7b0846c42b21a240` | `IndusInd_Bank.json` |
| `18a155ba09b5dd20185bcc47d71300833c3c05d72a73d784f6ec023be2a1c3a6` | `1f86d7871bfecd18dcf5820246268d5212523838d39e0582214c766d3bc2ec87` | `Info_Edg_India.json` |
| `dfba6e2d4527547106e98ecedff158a2d1300ef0e6c9eb3e74c980992b1fb94f` | `e2cc08fe3c88ffe9aae4640ed613ffb4a798894508a46c811bc1cb872cdd9962` | `Info_Edg_India_1.json` |
| `37dc13b4ed610031f85cdb37b4afa08fc21419711398dd4f3738b214a0d1ba88` | `3b54aa578c4bb80a0881aea183757aa27579854847232ca14294213661c9078a` | `Kotak_Mah__Bank.json` |
| `35f025cd7524d03d72a9113b2e6d1b7134c58062dda378c3053862cdcb5aa717` | `a9441cc6a4d30c73e932b8fd5eec7317e32ddb6fa3692cb04d08697c3da2ec23` | `Kotak_Mah__Bank_1.json` |
| `dc230881529f462543d22a69e63d8ca96c4cdf869619574d21c80ddac7da9f41` | `a4e98bbb5ce78a618b3b0740bc84dfed189b4ea52ea894bee1a392c88b621787` | `Muthoot_Finance.json` |
| `01292620bb31f9fe63b28ae30f57c0954fd833a5513aec7a43d49470c8c4d8ab` | `23a5512c3ad0404c788f9d7d55017a1d6f20fd1064cae8b7d2b756b1f1638d8e` | `New_India_Assura.json` |
| `6b235aec6651b9f1b3208217f784960d955a1b68eff0c4d00ffade0bf32ceef1` | `defd3abc95d50d7f01cad8302fe7168096ca26657503657c1a40d2249c03668d` | `New_India_Assura_1.json` |
| `5e8025a618bcdad60a7bb829c8227b0d08478c1700062b2bd5258b36e71bbc08` | `e95504cfed6c9007dc8d90c87a63e696b0fe630c52e15f9b5a3b9e3dd25957e5` | `Ola_Electric.json` |
| `8641011769db531a16d94a7b51547ea5f4d4b90625f0336e5a78a0a210621c9d` | `8af1accce08dd5fe3ad88214fcdf7be541922fff1f649c7aaa3b0162dc0b2a9b` | `One_97.json` |
| `a0b649d4675b4f3dbaea0ec64bb5f75867a485ea4712e73f16b8c8d767888c2d` | `2142392ce779f91fe420b6116dc4f8c329641e325c88601829160dcaed85f947` | `PB_Fintech.json` |
| `996005ef6d9dcd5603fd94a523cd9e4d8bc4d32dd6738684533967e76b8949da` | `5606d224261d1493bc455ef667bb13572d59607531d46b8964a878d44ccefa8c` | `PNB_Housing.json` |
| `7918de5163a0e99a0ed0b389e25c2eb25563554c0894a853076241424b53b9f6` | `894b0084b5d271d88af22fe2b0dc995d9287ddb3aeff5a69a56382945f5373c6` | `Punjab_Natl_Bank.json` |
| `1a99912e5271dd687b6f26e7eee7614cb4ea9a6a412098d0e4a34fcd9dd93d9f` | `d57ef167c9f2b491ab70fef2b00f67c94b0ecfaa5dbf6994796fab19f89ae115` | `Punjab_Natl_Bank_1.json` |
| `042a2d466e5c83a1e37afa3ef87cdfd9628d129b935f616f0aeda0d7b93e56aa` | `a4506402ac2543848c020db3f82e066dc46272d492a369e17352f5a588fb5b2a` | `Reliance_Industries_1.json` |
| `3f33c2492c94e16b1fa0deac987152b7a92904cadd23fe29530c4794144c1414` | `f8ad94d3393d6e61cbafc3f9cc114661babe0d241cae53abff1e8d78ab10225f` | `Reliance_Industries_2.json` |
| `73a0e2fb27c3c52871219fa33d0299bc7c11b766a4047a3a6a6bc06c5c6b27fe` | `a5e4ac05f7e7a86a77043c5a608503f48e9ea7a69fcc5b0a711d7b531685fafe` | `SBI_Life_Insuran.json` |
| `216a5c26c25dfa28b5a269a03171203414b20e0d4f7d2db5b27b1f24a265f978` | `cf70b14a9e92eca42ae0446e7da35a95e95a05e202b8b4b071486051a98b0321` | `SRF.json` |
| `75e82a7bb887382e94d44dcb9609fce829b17da55680f7d7adae6861d151eeeb` | `5efd6240d6d4d9e8128be1bf03634d67a0043f239bc1a9e0c8738c1bc3407dd3` | `Star_Health_Insu.json` |
| `80402f62f0989fe5cdfb2396b09c8a29a66b2a28f342f826acc2aa9ebb0d4593` | `f86e49194ad782a2f9dc35aadc05795e1fda9988aba78c91db8a4626ea6f40eb` | `Swiggy.json` |
| `1ecda3744f11079c2fad5b00f458efc576da42a1f7a2c3259e133d5715cc686b` | `bdd7e4b2d370ef6f1183dee5c3ddb397ed3b5ee405824ee47ef5e90adc4b7dc3` | `TCS_1_1.json` |
| `c4bac255a4bda4f329da9006503be15d9108da123a3a8a9457e3a99fad20446c` | `785856a89daffa802ef36c08371c58f479a0267d06872cc92a5f87b78b0685d0` | `Tata_Motors_1.json` |
| `14163f4d412e18c51d3f45cf169701effd596f7da62dbb7f6df4e06ef086ed05` | `0d5f39c0d92834c4c5f37ed2f9e476fe1b676d289ba198b8b5dd8f482de02b45` | `Tata_Motors_PVeh_1.json` |
| `d0d6e407f711e50ffdd86f09fc187bf7b62569b62d294534ca5a8c5d136c19a1` | `73184ad11d1033e424440f78839cf5eaa2aba92da8f7b11728c0b590253471c8` | `Tata_Power_Co_2.json` |
| `aecc51521426e24c5a613f380c1019b7645e630614bc6956416a287f75fb20ff` | `74308e0ad3d60a4d396e799547024ccb6ae569f15d5e81cf5bdd3fd122849b9d` | `United_Spirits.json` |

## Industry classification (batch H, NSE quote API)

Fetched 2026-11-15 17:58 UTC from a cloud container with the project's `PoliteFetcher` (project User-Agent, no
warm-up, 1.5 s apart). URL: `https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=EQ&symbol=<SYM>`
(`M&M` sent as `M%26M`). Saved byte-for-byte; the price fields are the 13-Nov-2026 close (`lastUpdateTime`).

| File | Symbol / ISIN | Classification (macro / sector / industry / basic industry) | SHA-256 |
|---|---|---|---|
| `classification/GetQuoteApi_getSymbolData_TCS.json` | TCS, INE467B01029 | Information Technology / Information Technology / IT - Software / Computers - Software & Consulting | `b41b0ebba524f5534a267243d8f91e4aaa7bc9a40fcdbe8e7337a8a2109a81df` |
| `classification/GetQuoteApi_getSymbolData_HDFCBANK.json` | HDFCBANK, INE040A01034 | Financial Services / Financial Services / Banks / Private Sector Bank | `aba013aa625e0dc3776a753946b9587efb9e4dcf971567af5830cd934b4e72e9` |
| `classification/GetQuoteApi_getSymbolData_M_M.json` | M&M, INE101A01026 | Consumer Discretionary / Automobile and Auto Components / Automobiles / Passenger Cars & Utility Vehicles | `9ad18793098f4a29b454ff8a7e08337c505ef32a427298841526ef5ab1e293bf` |

## NSE daily PR zip (market-cap file; fetched 2026-11-17, one request each, >= 1.2 s apart)

`PRddmmyy.zip` from `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/` (HTTP 200, curl with a browser
User-Agent, no warm-up). Read by `tests/test_mcap_universe.py` [X130-X134]. 114 further zips (every week end
2024-10-04 .. 2026-11-08 and six quarter ends) were fetched for the live analysis and are not committed.

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `pr_zip/PR011024.zip` | First in-scope trading day (C9); member `MCAP01102024.csv` (upper case); RELIANCE before its 1:1 bonus, ADANIPOWER before its 1:5 split; ELIN Issue Size = X114 FY25 issued | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR011024.zip` | `45bf29c9ff8eb49fe4e79c624c260b60e7c23c523c8d17496becf6871aa85956` |
| `pr_zip/PR300625.zip` | Mid-2025 quarter end: same header and layout | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR300625.zip` | `68212caa54a45112b30b2adb85e20ce86dce48807efce25c9be792d58946b6e3` |
| `pr_zip/PR300926.zip` | Quarter end of the ELIN Reg. 31 fixture (`xbrl/SHP_1739151_15102026054406_WEB.xml`): Issue Size = Reg. 31 total | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR300926.zip` | `d82bcd64f2f0b78540dd40b705c9f8297485e13622def4f6f83b6a1a97223307` |
| `pr_zip/PR131126.zip` | Latest file; member `mcap13112026.csv` (lower case), 14 members | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR131126.zip` | `c0eebe6666cd64ea4096be7589c740e050f189289f2760a5ac66c60146ec6377` |

## Permitted securities and BSE (owner 2026-11-17; X165-X168, A16-A18)

NSE listings fetched 2026-11-17 from the container (financials.fetch.http, >= 1.5 s apart), saved unmodified. BSE bhavcopy fetched 2026-11-17 by plain HTTP from the container; a GitHub runner fetched byte-identical bytes the same day (probe run 1). Files under `bse/` other than the bhavcopy are copied unmodified from the owner's repository `Pareshking/NSE-BSE-Insider-Tracker` (`tests/fixtures/bse/`, read-only clone 2026-11-17); that repository describes them as real BSE answers fetched 12-13 Oct 2026 and **trimmed** there (subsets of rows; the JSON announcements file is the `Table` row list only), so their bytes are not BSE's answer as sent; the SHP files are one filing each, gzip-compressed there.

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `discovery/nse_integrated-filing-results_equities_ABBOTINDIA_20261117.json` | X166: Integrated Filing listing of a `Permitted` security (ABBOTINDIA) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=ABBOTINDIA` | `085a784f77c3484bd864a2b83e4600fb3b86143c056484cd966d769aa50c4c10` |
| `discovery/nse_annual-reports-xbrl_equities_ABBOTINDIA_20261117.json` | X166: Reg. 34 annual XBRL listing of a `Permitted` security (ABBOTINDIA) | `https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=ABBOTINDIA` | `8fe32e407a1038ee38753b70e5374b3a46d6ae9d5f16cd5b73c53abaca8f5ed0` |
| `discovery/nse_corporate-share-holdings-master_equities_ABBOTINDIA_20261117.json` | X166: shareholding master of a `Permitted` security (ABBOTINDIA) | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=ABBOTINDIA` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `discovery/nse_integrated-filing-results_equities_MCX_20261117.json` | X166: Integrated Filing listing of a `Permitted` security (MCX) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=MCX` | `085a784f77c3484bd864a2b83e4600fb3b86143c056484cd966d769aa50c4c10` |
| `discovery/nse_annual-reports-xbrl_equities_MCX_20261117.json` | X166: Reg. 34 annual XBRL listing of a `Permitted` security (MCX) | `https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=MCX` | `8fe32e407a1038ee38753b70e5374b3a46d6ae9d5f16cd5b73c53abaca8f5ed0` |
| `discovery/nse_corporate-share-holdings-master_equities_MCX_20261117.json` | X166: shareholding master of a `Permitted` security (MCX) | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=MCX` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `discovery/nse_integrated-filing-results_equities_BAYERCROP_20261117.json` | X166: Integrated Filing listing of a `Permitted` security (BAYERCROP) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=BAYERCROP` | `085a784f77c3484bd864a2b83e4600fb3b86143c056484cd966d769aa50c4c10` |
| `discovery/nse_annual-reports-xbrl_equities_BAYERCROP_20261117.json` | X166: Reg. 34 annual XBRL listing of a `Permitted` security (BAYERCROP) | `https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=BAYERCROP` | `8fe32e407a1038ee38753b70e5374b3a46d6ae9d5f16cd5b73c53abaca8f5ed0` |
| `discovery/nse_corporate-share-holdings-master_equities_BAYERCROP_20261117.json` | X166: shareholding master of a `Permitted` security (BAYERCROP) | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=BAYERCROP` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `discovery/nse_integrated-filing-results_equities_HAWKINCOOK_20261117.json` | X166: Integrated Filing listing of a `Permitted` security (HAWKINCOOK) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=HAWKINCOOK` | `085a784f77c3484bd864a2b83e4600fb3b86143c056484cd966d769aa50c4c10` |
| `discovery/nse_annual-reports-xbrl_equities_HAWKINCOOK_20261117.json` | X166: Reg. 34 annual XBRL listing of a `Permitted` security (HAWKINCOOK) | `https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=HAWKINCOOK` | `8fe32e407a1038ee38753b70e5374b3a46d6ae9d5f16cd5b73c53abaca8f5ed0` |
| `discovery/nse_corporate-share-holdings-master_equities_HAWKINCOOK_20261117.json` | X166: shareholding master of a `Permitted` security (HAWKINCOOK) | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=HAWKINCOOK` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `discovery/nse_integrated-filing-results_equities_GOODYEAR_20261117.json` | X166: Integrated Filing listing of a `Permitted` security (GOODYEAR) | `https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol=GOODYEAR` | `53574ed3b5e0e1c6c33eac0399277efecea8f3401201db315635d6abf4c5ae5b` |
| `discovery/nse_annual-reports-xbrl_equities_GOODYEAR_20261117.json` | X166: Reg. 34 annual XBRL listing of a `Permitted` security (GOODYEAR) | `https://www.nseindia.com/api/annual-reports-xbrl?index=equities&symbol=GOODYEAR` | `8fe32e407a1038ee38753b70e5374b3a46d6ae9d5f16cd5b73c53abaca8f5ed0` |
| `discovery/nse_corporate-share-holdings-master_equities_GOODYEAR_20261117.json` | X166: shareholding master of a `Permitted` security (GOODYEAR) | `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=GOODYEAR` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` |
| `bse/BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV` | X165: BSE equity UDiFF bhavcopy, FinInstrmId = BSE scrip code, ISIN per row (5,141 rows) | `https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_20261113_F_0000.CSV` | `3151fc64585f9071603ca55373017d60ad05a243e77ab62fc69df2d01ec8dda9` |
| `bse/announcements.json` | A17: announcements rows (68, one per category / subcategory of 12 Oct 2026; trimmed in the source repo) | `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=N&strCat=-1&strPrevDate=20261012&strScrip=&strSearch=P&strToDate=20261012&strType=C&subcategory=-1` (source repo `tests/fixtures/bse/announcements.json`) | `99ccb4572bcaa2754b026ba210a0e0a1427932a3085fb324d4f96b7e67017ef5` |
| `bse/shareholding_listing_20261012.json` | A17: shareholding filings list (15 rows, trimmed in the source repo) | `https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w?scripcode=&flag=<n>&indtype=` (source repo `tests/fixtures/bse/shareholding_listing_20261012.json`) | `9ea4243d2bfde1981df095920975bf012890bded9e808790af71ce00d7bfe41b` |
| `bse/shp_500014_20260930.html.gz` | A17 / X167: one shareholding filing's inline XBRL (gzip of the HTML), SEBI `in-bse-shp` 2025-10-31 taxonomy | `https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/500014_1210202623725_SP.html` (source repo `tests/fixtures/bse/shp_500014_20260930.html.gz`) | `4c9cde765d2e922547ffca2dfa9ee5aec11878ee4342f3f8ee0b3ce0fa3ff7cc` |
| `bse/shp_542117_20260930.html.gz` | A17 / X167: one shareholding filing's inline XBRL (gzip of the HTML), SEBI `in-bse-shp` 2025-10-31 taxonomy | `https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/542117_12102026224350_SP.html` (source repo `tests/fixtures/bse/shp_542117_20260930.html.gz`) | `fe0b329250a377c70aa956ac5a0d76090191123cd6340674c9d78986f3aecff2` |
| `bse/shp_542910_20260930.html.gz` | A17 / X167: one shareholding filing's inline XBRL (gzip of the HTML), SEBI `in-bse-shp` 2025-10-31 taxonomy | `https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/542910_12102026182749_SP.html` (source repo `tests/fixtures/bse/shp_542910_20260930.html.gz`) | `a72a2205c4af08297a4abb4e87dfa543e7f7a7a179d9aad6c206761631a00aff` |
| `bse/bse_ListofScripData_GroupA_20261117.json` | X169 / A18: BSE list of securities, group A (705 rows), probe run 2 on a GitHub runner (run 44029015234), plain requests with the ported headers; ledger blob saved unmodified | `https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?scripcode=&Group=A&industry=&segment=Equity&status=Active` | `b6847c4e156b90720981ee3397f76d744a69768ac25371b7acefc3f561a7e9bd` |
| `bse/bse_ListofScripData_A_500488_20261117.json` | A18 / X169: list of securities narrowed to scrip 500488 (one row); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified | `https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?scripcode=500488&Group=A&industry=&segment=Equity&status=Active` | `18e4ed666d920f6baf16a51c05572efc8788e3c65d07385feb0a3604d0995195` |
| `bse/bse_AnnSubCategoryGetData_500488_20261015_20261117.json` | A18 / X168: ABBOTINDIA announcements 15 Oct-17 Nov 2026, every category (4 rows, ROWCNT 4); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified | `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate=20261015&strScrip=500488&strSearch=P&strToDate=20261117&strType=C&subcategory=-1` | `467e7191109f82599c6db8ea0b5b99c5be25e981d90d7e9b3aa88acd70c121a1` |
| `bse/bse_AnnSubCategoryGetData_all_20261113_p1.json` | A18 / X168: every company's announcements of 13 Nov 2026, page 1 (50 rows, ROWCNT 2,704), the source client's exact call; probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified | `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1&strPrevDate=20261113&strScrip=&strSearch=P&strToDate=20261113&strType=C&subcategory=-1` | `0d2dab29f25d5cd22dedabadd8ba3445a6188900f90b2120e2d2743022d41211` |
| `bse/AttachLive_e334e776-71a5-4afd-adf3-ad10a11505cf.pdf` | A18 / X168: the attachment of ABBOTINDIA's Q2 FY27 'Result' announcement (PDF, size = Fld_Attachsize); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified | `https://www.bseindia.com/xml-data/corpfiling/AttachLive/e334e776-71a5-4afd-adf3-ad10a11505cf.pdf` | `cd242440c638091ce9ab73d010e2120c6d3e3908d73c79f69411dc0c17d6b6d6` |
| `bse/bse_Corp_Shareholding_ng_500488_flag6_20261117.json` | A18: shareholding filings of 500488 for the last year (flag 6, 4 rows, inline-XBRL links, broadcast `D`); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified | `https://api.bseindia.com/BseIndiaAPI/api/Corp_Shareholding_ng/w?scripcode=500488&flag=6&indtype=` | `5bcdd4441c9e53d6c8d86aff5dc9c9357b040de27bfe268c1ce7ff38e9a3809c` |
| `bse/500488_14102026161949_SP.html` | X170: ABBOTINDIA Reg. 31 pattern as of 30 Sep 2026, BSE inline XBRL (707 nonFraction + 64 nonNumeric facts), as sent (not gzipped); probe run 3 on a GitHub runner (run 44030916910, 2026-11-17, plain requests with the ported headers); ledger blob saved unmodified | `https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/500488_14102026161949_SP.html` | `13ef8060c804e9c5a8ce77370bd7e44c7e280aa2530259b75362f66b70293093` |

## BSE list rule BSE2 (2026-11-17, runner ledger of bse-fetch run 44125439750, bytes as sent, sha256 verified)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `bse/bse_ListofScripData_GroupY_20261117.json` | X200 BSE2: BSE group Y list of securities, 2 rows, ISIN "" (A D S Diagnostics 523031) and "NA" (Pushpsons 531562) (fetched 2026-11-17T16:26:51Z on a runner) | `https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?scripcode=&Group=Y&industry=&segment=Equity&status=Active` | `401abd920ffafe870716707ddb6883d60a5c1be5e491e21468816397990396e5` |
## QY: YTD context copying the quarter (copied 2026-11-17 from the local vault blob, gunzipped, sha256 verified)

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `ytd_copy/INTEGRATED_FILING_INDAS_1624500_12022026071533_WEB.xml` | Ajax Engineering Q3 FY26 standalone: the Apr-Dec 2025 context repeats the Oct-Dec values to the rupee (revenue 4,335.48 Mn, PAT 382.41 Mn) (X173) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1624500_12022026071533_WEB.xml` | `e79b8dca9f3d341d3da59bf8181c1f6b72defb1360b9cc97d1f17c0cdfac991f` |
| `ytd_copy/INTEGRATED_FILING_INDAS_1501178_02082025064022_WEB.xml` | Ajax Engineering Q1 FY26 standalone: revenue 4,665.15 Mn, the earlier quarter that proves the 9M a copy (X173) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1501178_02082025064022_WEB.xml` | `70274f378369b27f7a4d3a72e10080c3035af7d5a5fb2346fefe11ea39e810a5` |
| `ytd_copy/INTEGRATED_FILING_INDAS_1573866_13112025063241_WEB.xml` | Ajax Engineering Q2 FY26 standalone: revenue 4,448.10 Mn and a genuine H1 YTD the rule leaves alone (X173) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1573866_13112025063241_WEB.xml` | `51643f65a7b2479351e9c40db18e2063d64ec4c54f6c5c16556ea53fcf9a2e23` |
## QC: universe expansion audit (share cross-check, attribution; X187-X189)

Copied byte-for-byte from the vault (gunzip only; sha256 equals the blob sha256) on 2026-11-17. Kept in
`xbrl_qc/` so the end-to-end fixture glob (`xbrl/*.xml`) and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl_qc/SHP_1743042_21102026043910_WEB.xml` | BLSE Reg. 31 30-Sep-2026 (90,856,485 shares) [X187] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1743042_21102026043910_WEB.xml | `ceb6aa4553bf90fbd611186ca623ed81cb914fcbe7758acf58558c3443bc1fff` |
| `xbrl_qc/INTEGRATED_FILING_INDAS_1751399_02112026072220_WEB.xml` | BLSE Q2 FY27 standalone, face value Rs 5 after the 6-Oct-2026 split [X187] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1751399_02112026072220_WEB.xml | `d7018cf50fa835c5bb0d6842248a8137c77187d6c7c63fc0f5cbbf97b35d1ded` |
| `xbrl_qc/SHP_1740781_17102026035440_WEB.xml` | KKCL Reg. 31 30-Sep-2026 (61,625,185) [X188] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1740781_17102026035440_WEB.xml | `3d1c8daf6d98eaa394c7da1b7c3f477db17621073e18033e7181fe6acbf279a9` |
| `xbrl_qc/INTEGRATED_FILING_INDAS_1751446_02112026075601_WEB.xml` | KKCL Q2 FY27 results [X188] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1751446_02112026075601_WEB.xml | `6707fd7195b417b06adde86d67f318a406922965f76d05d6a5587687a01702fe` |
| `xbrl_qc/INTEGRATED_FILING_INDAS_1751447_02112026075620_WEB.xml` | KKCL Q2 FY27 results, whole crores, paid-up 62 Cr [X188] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1751447_02112026075620_WEB.xml | `98a4990209db5204dad1eb1fd69613a646ed22a0aca5f6eaedd701b7d7810d07` |
| `xbrl_qc/SHP_1702639_28072026113716_WEB.xml` | ATLANTAELE Reg. 31 30-Jun-2026 [X188] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1702639_28072026113716_WEB.xml | `80f3fcfc9381c0ec143414e9f6063083c7a2f42e7f38ce4dde4c82576f0bc7b1` |
| `xbrl_qc/INTEGRATED_FILING_INDAS_1697896_21072026124625_WEB.xml` | ATLANTAELE Q1 FY27 standalone, paid-up capital tagged 0 [X188] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1697896_21072026124625_WEB.xml | `ea5e534ecd1712cea0e580e2dbc33066b1ccbb0ecf6e932d438f27ccc0ff2161` |
| `xbrl_qc/INTEGRATED_FILING_INDAS_1454124_28052025104806_WEB.xml` | DPSCLTD Q4 FY25 consolidated, owners = PAT before JV share, NCI 0 [X189] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1454124_28052025104806_WEB.xml | `124ef7afb9eefa407153204f6cd39dc9363577df356305d4149598b69b8874ce` |
| `xbrl_qc/INTEGRATED_FILING_INDAS_1667760_15052026050235_WEB.xml` | GOKULAGRO Q4 FY26 consolidated, owners = PAT before associates, NCI 0 [X189] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1667760_15052026050235_WEB.xml | `e8e80236ea0ce67ceedc30845bcbb24ab1841780230bbd5d0967e2cd15fa729a` |

## QY2: LevelOfRounding slip of one filing (X201; copied 2026-11-17 from the local vault blob, gunzipped, sha256 verified)

Kept in `level_slip/` so the end-to-end fixture glob (`xbrl/*.xml`) and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `level_slip/INTEGRATED_FILING_INDAS_1705022_30072026030857_WEB.xml` | IMPAL Q1 FY27 standalone declares `Lakhs`, values typed in crores: total income 24,396,000, paid-up 1,248,000 (X201 slip, factor 100) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1705022_30072026030857_WEB.xml` | `cb847c05bfdc629bdeb8e3c92705cb0beed010b23f7404851c6a94c2b570a967` |
| `level_slip/INTEGRATED_FILING_INDAS_1748931_29102026045421_WEB.xml` | IMPAL Q2 FY27 standalone `Crores`: H1 total income 4,825,900,000 = Q2 2,386,300,000 + 243.96 Cr; paid-up 124,800,000 (X201 neighbour) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1748931_29102026045421_WEB.xml` | `54701505dc14e9a9c40c98f4c287e7598eb075e1f7545fb1d19f1fcd415f7c33` |
| `level_slip/SHP_1697471_20072026072756_WEB.xml` | IMPAL Reg. 31 30-Jun-2026: 12,480,000 shares (x Rs 10 = the Q2 paid-up) (X201) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1697471_20072026072756_WEB.xml` | `1d1d069bd061fb15243cf31813d979812dbf7739f525f50a26464e522012cf23` |
| `level_slip/INTEGRATED_FILING_INDAS_1507427_08082025074055_WEB.xml` | Mamata Machinery Q1 FY26 standalone declares `Millions`, values typed in lakhs: revenue 2,757,910,000, paid-up 2,460,780,000 (X201 slip, factor 0.1) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1507427_08082025074055_WEB.xml` | `95d97d72dc73e31e7acf5422d19205430514efca251fc17bf2ccb3257146df5c` |
| `level_slip/INTEGRATED_FILING_INDAS_1569007_08112025020703_WEB.xml` | Mamata Machinery Q2 FY26 standalone `Lakhs`: H1 revenue 679,399,000 = Q2 403,608,000 + Q1 275,791,000 (the filed 2,757,910,000 / 10); paid-up 246,078,000 (X201 neighbour) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1569007_08112025020703_WEB.xml` | `bd20546f372527550fa0a9fe5fb27541939bf9ca2e02ff8b194413a2793fdf79` |
| `level_slip/SHP_1583648_08122025123811_WEB.xml` | Mamata Machinery Reg. 31 30-Jun-2025: 24,607,800 shares (X201) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1583648_08122025123811_WEB.xml` | `d8813e70aa6ea4621d45b53e9dca3ffd2f945957acd3f6d909515ec6080ff66e` |
| `level_slip/INTEGRATED_FILING_INDAS_1609342_23012026054425_WEB.xml` | Gandhar Oil Q3 FY26 standalone `Crores` after `Millions`: a permanent, genuine unit change (paid-up 195,800,000 = SHP shares x Rs 2), not rescaled (X201 negative) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1609342_23012026054425_WEB.xml` | `f4515786f0d03b207902023a7777fbe6c32514fd6dcf6dd8e3fe71c2ae7eb5d0` |
| `level_slip/INTEGRATED_FILING_INDAS_1572275_12112025050504_WEB.xml` | Gandhar Oil Q2 FY26 standalone `Millions` (X201 negative) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1572275_12112025050504_WEB.xml` | `d7f5e250e831e9d1714af1bb1c80fd52d14f6d353163c7e9310439d6b54a23f3` |
| `level_slip/SHP_1605763_20012026045734_WEB.xml` | Gandhar Oil Reg. 31 31-Dec-2025: 97,879,530 shares (X201 negative) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1605763_20012026045734_WEB.xml` | `187af37eab86435acc12b62c22dcc57f70126e72ea8523cb6d5770604841062f` |

## QC2: universe expansion, NEW entities (share cross-check, attribution by EPS; X211-X214)

Copied byte-for-byte from the vault (gunzip only; sha256 equals the blob sha256) on 2026-11-17. Kept in
`xbrl_qc2/` so the end-to-end fixture glob (`xbrl/*.xml`) and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1743401_21102026064421_WEB.xml` | BLSE Q4 FY25 consolidated re-sent 21-Oct-2026 after the 6-Oct-2026 split, face value Rs 10, 90,856,500 shares [X211] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1743401_21102026064421_WEB.xml | `3a533267606d9b84d852af2ea412c3be2443d14a21063d3cdaaca356adc21665` |
| `xbrl_qc2/SHP_197284_1415020_15042025053836_WEB.xml` | BLSE Reg. 31 31-Mar-2025 (90,856,485) [X211] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_197284_1415020_15042025053836_WEB.xml | `a98ea7769d95d2ac1c39eca73906f3e122769324bc3cde17a3da14e684dd4afa` |
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1510694_13082025021504_WEB.xml` | Selan Q1 FY26 standalone, paid-up 35.16 Cr after the allotment at the results meeting of 12-Aug-2025 [X212] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1510694_13082025021504_WEB.xml | `658290cee769512f36882beb91c148af45360d88279411394236c4984ed1f2a9` |
| `xbrl_qc2/SHP_1485504_17072025045200_WEB.xml` | Selan Reg. 31 30-Jun-2025 (15,200,000) [X212] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1485504_17072025045200_WEB.xml | `60779ceaac2e8b49e19067fc0ebec3e7e7f2b705908def03868ece34be5ce204` |
| `xbrl_qc2/SHP_1515913_21082025073534_WEB.xml` | Selan Reg. 31 dated on the allotment 12-Aug-2025 (35,162,358; SHP17) [X212] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1515913_21082025073534_WEB.xml | `c59fad8baf26fa92c9d290e0711f2f6d7c3701f0a59555d55c22d95aea6fa645` |
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1757893_13112026081803_WEB.xml` | Davangere Sugar Q2 FY27 standalone, 1,695,896,000 shares of Re 1 = NSE Issue Size of 13-Nov-2026 [X212] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1757893_13112026081803_WEB.xml | `18f2ad4eb9bde76dcdb9af0e5ea08987a81ba7a46f20225656b26fecfa6f487e` |
| `xbrl_qc2/SHP_1742915_21102026035238_WEB.xml` | Davangere Sugar Reg. 31 30-Sep-2026 (1,429,990,798) [X212] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1742915_21102026035238_WEB.xml | `43613006dc749da95763f82611f3cf6efe2d7c9d5cc13c840a28161d26074513` |
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1449578_23052025092633_WEB.xml` | Digispice Q4 FY25 standalone, paid-up 62.2665 Cr / Rs 3 net of trust-held shares [X213] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1449578_23052025092633_WEB.xml | `ece98a7171f74129a7a95406bb6593dbde4b38a019c25c1857876af05e96463e` |
| `xbrl_qc2/SHP_198927_1422138_21042025100818_WEB.xml` | Digispice Reg. 31 31-Mar-2025 (233,623,106; two trusts named under non-institutions "Others") [X213] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_198927_1422138_21042025100818_WEB.xml | `2b9be41f2598dfe79f535ae8cfe07099369f06cd34f96f9cd0b577feb2d93abc` |
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1567276_06112025071457_WEB.xml` | Ajmera Realty Q2 FY26 consolidated, owners filed 0, NCI 87 lakh [X214] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1567276_06112025071457_WEB.xml | `eef2b9cf9600479a26dbebfd928a801ba00a7857c29772555182b35a1a7519f0` |
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1598932_12012026052921_WEB.xml` | Bajaj Indef Q2 FY26 consolidated re-filing, owners 0, NCI +3.5 lakh (PDF (3.50)) [X214] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1598932_12012026052921_WEB.xml | `cf608c041bffdc6fe9e83835aa44aa0e7cf72b7006beb6ed154742e85f8bf091` |
| `xbrl_qc2/INTEGRATED_FILING_INDAS_1439263_14052025102806_WEB.xml` | Nilkamal Q4 FY25 consolidated, owners agree with EPS, PAT line does not [X214] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1439263_14052025102806_WEB.xml | `af47cff30b663b9c941e25d6c0a184b41ded9df163afbe6b7162a7f3fc0658fb` |

## QS: rule SHARES_REG31_OUTLIER (X221; copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified)

Read by `tests/test_x221_reg31_outlier.py`. The PR zip is the vault blob as fetched (stored uncompressed).

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `shares_outlier/SHP_1696707_20072026025841_WEB.xml` | MBLINFRA Reg. 31 30-Jun-2026: TOTAL 155,879,256 shares (the outlier against results and NSE until the 30-Sep-2026 listing) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1696707_20072026025841_WEB.xml` | `ea538ab6ccb2b81c9374d92b17f0d558715e71de29be55dfa4e91fa87dbc38ea` |
| `shares_outlier/INTEGRATED_FILING_INDAS_1700387_23072026082824_WEB.xml` | MBLINFRA Q1 FY27 standalone results: paid-up 152.53 Cr of Rs 10 = 152,530,000 shares | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1700387_23072026082824_WEB.xml` | `18732b9de8e373b347a75b2970c8cb3ee3418de5da5aad35c7d1f69e8a46df77` |
| `shares_outlier/SHP_1739920_16102026040314_WEB.xml` | HMT Reg. 31 30-Sep-2026: TOTAL 1,204,091,640 shares (all three counts differ) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1739920_16102026040314_WEB.xml` | `51ddf496191c356069e49066182b6360c0cdcc6ffd447fba3710d98bc0f08b45` |
| `shares_outlier/INTEGRATED_FILING_INDAS_1755096_06112026073646_WEB.xml` | HMT Q2 FY27 standalone results: paid-up 355.60 Cr of Rs 10 = 355,600,000 shares | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1755096_06112026073646_WEB.xml` | `0a03f319fdd01e21b7e35985d9c163ce3be4fb7c93585dab403458a65a98c155` |
| `pr_zip/PR250926.zip` | PR zip of 25-Sep-2026: MBLINFRA Issue Size 152,529,256 (= results paid-up / face, Reg. 31 the outlier; 155,879,256 in `PR300926.zip`) | `https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR250926.zip` | `03c07898138cb6b62ccef18f902cd14b397bae2f68996cc726fb0a2889f560af` |

## QF3: rule YTD_MISFILED_NO_BRIDGE (X226; copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified)

Read by `tests/test_x226_misfiled_ytd.py`. Kept in `ytd_misfiled/` so the end-to-end fixture glob (`xbrl/*.xml`) and
its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1510585_12082025093306_WEB.xml` | NAZARA Q1 FY26 consolidated: PAT 51.34 Cr (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1510585_12082025093306_WEB.xml` | `2204d8f72d79b15a241e780b01f12f7b8d95c3526ee27d259989a37045554837` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1573094_12112025104605_WEB.xml` | NAZARA Q2 FY26 consolidated: Q2 PAT -33.93 Cr, H1 17.41 Cr (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1573094_12112025104605_WEB.xml` | `22a1fb19f599d2dcbf3e021f06f212667ddc8e702d4a8b6647371ab27b96c18c` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1617405_03022026063441_WEB.xml` | NAZARA Q3 FY26 consolidated: Q3 PAT 8.84 Cr (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1617405_03022026063441_WEB.xml` | `f419fadd37dab4168eecdcba2e0279c67b2d4887079d1dd7cc73898c9fd9a0f5` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1666284_12052026113715_WEB.xml` | NAZARA Q4 FY26 consolidated results: Q4 PAT 55.70 Cr, FY 81.94 Cr (= the quarters) (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1666284_12052026113715_WEB.xml` | `d627c73986bb20deb727de87547a5904b151f405de567a990806c83fe7085932` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1740461_16102026080647_WEB.xml` | NAZARA Q4 FY26 consolidated results re-sent 16-Oct-2026: Q4 PAT 55.70 Cr and PBT unchanged, FY PAT -23.24 Cr (the mis-filed YTD) (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1740461_16102026080647_WEB.xml` | `abd86bca94deb64fe69bb5b6abad36b1869633782e326b672adafbf08266681e` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1707299_03082026104926_WEB.xml` | NAZARA Q1 FY27 consolidated: PAT -82.47 Cr (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1707299_03082026104926_WEB.xml` | `509f9341b7c1c69f86a5faac28dd1840c8029cdca9f56ea9ec8100287f37a605` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1746358_26102026114756_WEB.xml` | NAZARA Q2 FY27 consolidated: Q2 PAT 35.36 Cr, H1 -47.11 Cr; the TTM row of X226 | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1746358_26102026114756_WEB.xml` | `e565fcdb853c9b660d49a3746687cf51723fad5c109f75bfcbd39a96abfb7ec4` |
| `ytd_misfiled/AR_XBRL_NAZARA_16112026123324.xml` | NAZARA FY26 Reg. 34 annual report (16-Nov-2026), consolidated FY PAT 81.94 Cr: the later filing that agrees with the quarters (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_NAZARA_16112026123324.xml` | `65c9d0e765c889dea9ed1c8fc9e94d70f45555b1ddd6dbf39a7e87073ad31623` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1510310_12082025074319_WEB.xml` | Aarti Pharmalabs Q1 FY26 consolidated: PAT 49.50 Cr (X226) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1510310_12082025074319_WEB.xml` | `d7b5907de385febaecb7ff50a2a9bbf49e98d8cd16b65ab20e153b5faa75fb06` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1569445_09112025092410_WEB.xml` | Aarti Pharmalabs Q2 FY26 consolidated: Q2 PAT 27.92 Cr, H1 filed -44.18 Cr (X226 PAT_SIGN_FLIP) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1569445_09112025092410_WEB.xml` | `534c6703650892fc39d47f2ff1f4b003ebcaf068aaca1903e11e0d918cf6c706` |
| `ytd_misfiled/INTEGRATED_FILING_INDAS_1622052_09022026083722_WEB.xml` | Aarti Pharmalabs Q3 FY26 consolidated: 9M PAT = Q1 + Q2 + Q3 (X226 NEXT_YTD_AGREES) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1622052_09022026083722_WEB.xml` | `77a635c217e481590ad0331dded32faeacf0fbf6ff7627fc6e572d9faac7324c` |

## QP3: annual prior-year check, rule X201 on annuals (X235) and RESTATED sub-classes (X233-X234); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x233_x235_annual_prior_year.py`. Kept in `level_slip_annual/` and `annual_restated/` so the
end-to-end fixture glob (`xbrl/*.xml`) and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `level_slip_annual/AR_XBRL_TDPOWERSYS_28082026104939.xml` | TD Power Systems FY26 consolidated Reg. 34 annual, `LevelOfRounding` Rupees with every amount typed in lakhs (revenue 185,623.38; equity capital 3,124.30) [X235] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_TDPOWERSYS_28082026104939.xml | `33a28c51ef6de47c7db43d44f2f6b4d70b5cc0cf6499f89d060306d1fd07902f` |
| `level_slip_annual/INTEGRATED_FILING_INDAS_1436604_12052025072108_WEB.xml` | TD Power Systems Q4 FY25 consolidated results (`Lakhs`): FY25 revenue 12,787,617,000, the stored side [X235] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1436604_12052025072108_WEB.xml | `3715019460f4505e46fbb787c0fadf31fbd919acf9797f3052cd48fecddfae30` |
| `level_slip_annual/INTEGRATED_FILING_INDAS_1667244_14052026070419_WEB.xml` | TD Power Systems Q4 FY26 consolidated results (`Lakhs`): neighbour paid-up capital and face value Rs 2 [X235] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1667244_14052026070419_WEB.xml | `29c430a507b72492f90ebd5145d71c4ee097c7f9e1054af351b43eef1496894f` |
| `level_slip_annual/SHP_1649607_13042026124938_WEB.xml` | TD Power Systems Reg. 31 31-Mar-2026 (156,214,830 shares) [X235] | https://nsearchives.nseindia.com/corporate/xbrl/SHP_1649607_13042026124938_WEB.xml | `8501c5e5123cd995d6be1f4891645388c022263938f6b7fe6c0373ae6369eca3` |
| `annual_restated/AR_XBRL_VINCOFE_11112026131428.xml` | Vintage Coffee FY26 consolidated annual: FY25 cash flows moved between activities, PAT / equity / net cash flow agree [X233] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_VINCOFE_11112026131428.xml | `783c944d38ba1e609332c8517a34fadf26b0f79dd0087fb42ee3e0e1578e22ac` |
| `annual_restated/INTEGRATED_FILING_INDAS_1433394_07052025082905_WEB.xml` | Vintage Coffee Q4 FY25 consolidated results (CFO -25.7608 Cr) [X233] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1433394_07052025082905_WEB.xml | `04a5c59061412c9c375b79de2bfdfdb8d73207ba445c697d9a4c2073d6b39b59` |
| `annual_restated/AR_XBRL_BASF_10092026090839.xml` | BASF India FY26 consolidated annual: FY25 re-presented for a discontinued operation (profit -4.80 Cr), PAT 479.06 Cr unchanged [X234] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_BASF_10092026090839.xml | `425ddd623b4c881991bf52ad557a300c2e750b8273a223aca6a33ab90d48529d` |
| `annual_restated/INTEGRATED_FILING_INDAS_1439467_15052025103557_WEB.xml` | BASF India Q4 FY25 consolidated results (revenue 15,339.45 Cr total income, no discontinued operation) [X234] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1439467_15052025103557_WEB.xml | `36e224498cd760908c7469821745d60422d0bae8624f319ec964c0c8e0ada9ec` |

## QB6: BSE CorpXbrlGen with Bsenewid and Scripcode (X246; bse-reach mode xbrl5, run 44262396799 on a GitHub runner, 2026-11-18, plain requests with the ported headers; ledger blobs saved unmodified)

Read by `tests/test_bse.py`.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `bse/CorpXbrlGen_500488_6fa639f3-1cba-42e1-a341-ab46e27899e6.xml` | X246: ABBOTINDIA's Q2 FY27 'Result' announcement (the NEWSID of `bse/bse_AnnSubCategoryGetData_500488_20261015_20261117.json`) as BSE's announcement XBRL, namespace `in-bse-co` 2017-06-21 (4,306 bytes, `text/xml`): ScripCode 500488, CategoryOfAnnouncement `Results`, TypeOfAnnouncement `Outcome`, ResultType `standalone`, AttachmentURL of `bse/AttachLive_e334e776-71a5-4afd-adf3-ad10a11505cf.pdf`; no financial statement facts | `https://www.bseindia.com/Msource/90D/CorpXbrlGen.aspx?Bsenewid=6fa639f3-1cba-42e1-a341-ab46e27899e6&Scripcode=500488` | `73e1cc11f8401f1e6f61af03ccb512abd2ec09840c6ddbf2ee9f722008e8001f` |
| `bse/CorpXbrlGen_590041_287a3321-71de-4a52-9089-083b8e94337f.html` | X246: the 21-byte `text/html` answer `Invalid Input Details` (same bytes for 544416 / NEWSID a114c4a1-7e95-42e0-93a2-2c61a9fa5142) | `https://www.bseindia.com/Msource/90D/CorpXbrlGen.aspx?Bsenewid=287a3321-71de-4a52-9089-083b8e94337f&Scripcode=590041` | `d236166591c9192fbdd94d7f4d01bd15e4ec2000d9b34bfe00c822add1a2c1ce` |
| `bse/beta_Comp_Resultsnew_expandable0_20261118.html` | X248: BSE's legacy ASP.NET results page on the beta host as first loaded (GET, 51,674 bytes, CRLF): form fields with two `name` attributes per control (`ctl00$ContentPlaceHolder1$broadcastdd` / `broadcast6`, `...$btnSubmit` / `submt6`), broadcast options 1-7, period options ALL / 3 / 2 / 1, results grid `ContentPlaceHolder1_gvData` whose Std / Con XBRL links are `__doPostBack` targets `...$gvData$ctl02$lnkXML` / `$lnkConXML` | `https://beta.bseindia.com/corporates/Comp_Resultsnew.aspx?expandable=0` | `e911d6242a002a310e339089674c0ab52f15dfbc9280ba9f23fc99e0491b5e35` |

## QD: rule X250 (reconciling lines filed as segment members); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x250_segment_labels.py`. Kept in `segments_qd/` so the end-to-end fixture glob (`xbrl/*.xml`)
and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `segments_qd/INTEGRATED_FILING_BANKING_1749476_29102026095319_WEB.xml` | Suryoday Small Finance Bank Q2 FY27 (Lakhs): `ReportableSegments5Member` labelled "Unallocated" next to four business segments [X250] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_BANKING_1749476_29102026095319_WEB.xml | `f08f4f2436b5f53943f60f68ac00c2e17bb2f90c7d2a0841516a4bb53bc71784` |
| `segments_qd/INTEGRATED_FILING_INDAS_1753986_05112026065300_WEB.xml` | SGLTL Q2 FY27: `ReportableSegments3Member` labelled "Eliminations", segment revenue -128,990,000 [X250] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1753986_05112026065300_WEB.xml | `2f8171264bf4a535b10ddd9a2593ac56980f8333009581ff805cd7419cae90b8` |

## QB7: BSE results XBRL (X247, X265; bse-reach mode xbrl6, run 44271899335 on a GitHub runner, 2026-11-18, plain requests with the ported headers; ledger blobs saved unmodified, sha256 = the ledger's; the NSE counterpart copied from the local vault blob, gunzipped, sha256 verified)

Read by `tests/test_bse_results_ixbrl.py`. Kept in `bse/` so the end-to-end fixture glob (`xbrl/*.xml`) and its
pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `bse/bse_Corp_GetFINANCE_DRDOWN_ng_flag1_20261118.json` | X247: the comp_resultsnew broadcast-period list: FlagDur 1 Today, 2 Last 1 Week, 3 Last 15 Days, 4 Last 1 month, 5 Last 3 month, 6 Last 1 year, 7 Beyond last 1 year | `https://api.bseindia.com/BseIndiaAPI/api/Corp_GetFINANCE_DRDOWN_ng/w?flag=1` | `2bd88fd94819b32da36d98422b631165c672300af8adb45bdaed1c85063c1841` |
| `bse/bse_Corp_GetFINANCE_DRDOWN_ng_flag3_20261118.json` | X247: result periods HFQ 3 Quarterly, 2 Yearly, 1 Half Yearly | `https://api.bseindia.com/BseIndiaAPI/api/Corp_GetFINANCE_DRDOWN_ng/w?flag=3` | `49d7715591166ceae9709b67b616007cb8c1919927ae5c1fc8d3889e6e372ee8` |
| `bse/bse_Corp_FinanceResult_ng_new_500488_flagdur6_20261118.json` | X247 / X265: ABBOTINDIA's results over the last year, 7 rows (SQ / SH 2026-27 .. DQ / DN 2025-26), 4 distinct standalone `XMLName` files, `Consol_XMLName` null, `Fld_CreateDate` IST | `https://api.bseindia.com/BseIndiaAPI/api/Corp_FinanceResult_ng_new/w?SCRIP_CD=500488&FlagDur=6&HFQ=&ISUBGROUP_CODE=&segment=C` | `ddcf8d96c088b89555ddaec9108e40af8565455beece3d8dd4447c643f11e7ed` |
| `bse/bse_Corp_FinanceResult_ng_new_all_flagdur1_20261118.json` | X247 / X265: every company's results of 18-Nov-2026 (SCRIP_CD blank, FlagDur 1): 4 rows of 544111 (PARKHOTELS) and 544477 (HILINFRA), with `Consol_XMLName` | `https://api.bseindia.com/BseIndiaAPI/api/Corp_FinanceResult_ng_new/w?SCRIP_CD=&FlagDur=1&HFQ=&ISUBGROUP_CODE=&segment=C` | `8116820f4a3eba70a387beb07a268bfa28aced1a9d45b9f79d73fe1c2b040718` |
| `bse/Integrated_Finance_Ind_As_500488_511202619052_IFIndAs.html` | X265: ABBOTINDIA (a Permitted member, no NSE XBRL) Q2 FY27 standalone results as inline XBRL (540,012 bytes, `text/html`): `in-capmkt` 2026-01-31 Integrated Finance Ind AS, 402 `ix:nonFraction` (scale 7, `ixt3:numdotdecimalin`, sign `-`) and 297 `ix:nonNumeric`, Symbol `NOTLISTED` | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_500488_511202619052_IFIndAs.html` | `47fd4cc3e3f259809a06e22a2dbf897387ca432350b1f8aeb729c6ae29dbaf5e` |
| `bse/Integrated_Finance_Ind_As_544111_18112026133342_IFIndAs.html` | X265 / R20: PARKHOTELS Q4 FY26 consolidated as BSE's inline XBRL (281,294 bytes), re-uploaded 18-Nov-2026 with LevelOfRounding `Crores` and a revised balance sheet | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_544111_18112026133342_IFIndAs.html` | `6f0dddbba91946f62fced9e7865e4ab4163f36a4f157a7c1b69cc5eac3faade9` |
| `bse/INTEGRATED_FILING_INDAS_1673679_27052026125706_WEB.xml` | X265 / R20: the NSE XML of the same company, period and scope (filed 26-May-2026, LevelOfRounding `Lakhs` on crore figures: the X201 slip, corrected x 100) | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1673679_27052026125706_WEB.xml` | `e74210e7a24509dd9539277168656b6b8fcc17d792b788fcf6ea93b0e35bc110` |

## QT: rule X273 (fixed-asset lines of a year end from one filing, owner decision T); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x273_fixed_assets.py`. Kept in `fixed_assets/` so the end-to-end fixture glob (`xbrl/*.xml`) and
its pinned counts are unchanged. Decision U (X274) reuses the QP3 `annual_restated/` pairs (no new file).

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `fixed_assets/INTEGRATED_FILING_INDAS_1670964_21052026084421_WEB.xml` | FSN E-Commerce (NYKAA) Q4 FY26 consolidated results: PPE 299.97 Cr, right-of-use assets 461.47 Cr as a labelled other non-current asset [X273] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1670964_21052026084421_WEB.xml | `b9acf086fe7731138585e2b47f68a47b792eab0cc30e0bf50650f9f82eb2c777` |
| `fixed_assets/AR_XBRL_NYKAA_23092026220941.xml` | NYKAA FY26 consolidated Reg. 34 annual: PPE 761.44 Cr including right-of-use assets, no separate line [X273] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_NYKAA_23092026220941.xml | `4a4ba20a1e231fe34dc16553e6d4c02b544e7c64d2fddccb1f48fab52f227dd3` |
| `fixed_assets/INTEGRATED_FILING_INDAS_1752762_04112026053637_WEB.xml` | NYKAA Q2 FY27 consolidated results: PPE 306.53 Cr, right-of-use 496.47 Cr (the neighbouring half-year) [X273] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1752762_04112026053637_WEB.xml | `4fe1d98c814a9d04c9c929041c256cfa7b28f246f481ff35aa2fc9279a112373` |
| `fixed_assets/INTEGRATED_FILING_INDAS_1668105_15052026092506_WEB.xml` | MPS Ltd (MPSLTD) Q4 FY26 consolidated results: goodwill 376.32 Cr, other intangibles 138.86 Cr [X273] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1668105_15052026092506_WEB.xml | `6d22eb0e46f3b8e8dca2a19be56f8d19a93ebbe65340918c5eb6bddc58904d03` |
| `fixed_assets/AR_XBRL_MPSLTD_01102026192529.xml` | MPSLTD FY26 consolidated Reg. 34 annual: other intangibles 494.10 Cr (class "Others" 439.54 Cr), no goodwill element [X273] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_MPSLTD_01102026192529.xml | `a8756e09f71d986402a995cfb5503d02f98f8b2d95d144050a7ab728fde8bd7a` |
| `fixed_assets/INTEGRATED_FILING_INDAS_1752323_03112026100325_WEB.xml` | MPSLTD Q2 FY27 consolidated results: goodwill 381.68 Cr, other intangibles 129.37 Cr (the neighbouring half-year) [X273] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1752323_03112026100325_WEB.xml | `7888ed7f1cb5052710022fda794c95eb4cd09aa12dbf5a5e35fcefacfcadbc8b` |

## R20 pair (2026-11-18, HILINFRA 544477 Q2 FY27 consolidated; BSE from bse-fetch run 44289837326, NSE from the vault)

| File | Why it is here | Source URL | SHA-256 |
|---|---|---|---|
| `bse/Integrated_Finance_Ind_As_544477_14112026175059_IFIndAs.html` | X266 R20: BSE inline XBRL of the same upload as the NSE XML below (17:50:59 IST) | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_544477_14112026175059_IFIndAs.html` | `7cf9950794ef40db7033a5322ee92e173d2d4df8aee4959d11c32444aa5571c4` |
| `bse/INTEGRATED_FILING_INDAS_1758435_14112026055150_WEB.xml` | X266 R20: NSE XML of the same upload (17:51:50 IST), gunzipped vault blob | `https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1758435_14112026055150_WEB.xml` | `4aa398ec87578ee68d32bdd20c1e73bb79a6c9c81261d3c33a1254f869319a66` |

## QB8: BSE results inline XBRL quarantined by batch 1 of the BSE results fetch (X280-X283; vault blobs of the bse-fetch runner ledger, imported unmodified, plain `.html` in the vault, sha256 verified = blob)

Read by `tests/test_qb8_bse_ixbrl_rules.py`. Kept in `bse/` so the end-to-end fixture glob (`xbrl/*.xml`) and its
pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `bse/Integrated_Finance_Ind_As_523862_1411202516851_IFIndAs.html` | X280: Q2 FY26 consolidated (523862), `WhetherCashFlowStatementIsApplicableOnCompany` displayed `true` under `ixt2:booleantrue` (153 batch-1 files failed on this element) | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_523862_1411202516851_IFIndAs.html` | `3b7024ca22e9e72b344799d39566e7ad6828123e33bbcd0577d440f14f4f27fa` |
| `bse/Integrated_Finance_Ind_As_539607_132202620589_IFIndAs.html` | X280: Q3 FY26 consolidated (539607), `DeclarationPursuantToClauseDOfSubRegulation3OfRegulation33OfSEBILODRRegulation2015` displayed `false` under `ixt2:booleantrue` | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_539607_132202620589_IFIndAs.html` | `75dca24dbfe294da722163e3270160e9d707af07e655f48e4498d63f95b91fba` |
| `bse/Integrated_Finance_Ind_As_513536_128202520028_IFIndAs.html` | X281 / X283: Q1 FY26 consolidated (513536), 6 unclosed `<BR>` inside the notes text block (not well-formed XHTML), reporting period displayed but not tagged | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_513536_128202520028_IFIndAs.html` | `6509895a1b5fc83ecc45425ecc086cd0b030c9c62705853076420623b8a5dfd8` |
| `bse/Integrated_Finance_Ind_As_539607_25112025201023_IFIndAs.html` | X282: Q2 FY26 standalone (539607), the empty "additional disclosure of related party transactions" table opens `<thead>` and closes it with `</tbody>` | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_539607_25112025201023_IFIndAs.html` | `2362afd3acdd78c8d585e52ed33ffa598806ddf42dea4e2541f0241ce52b9c25` |
| `bse/Integrated_Finance_Ind_As_504731_88202519641_IFIndAs.html` | X283: Q1 FY26 consolidated (504731), well-formed, reporting period displayed as plain text only (NO_DECLARED_PERIOD at 0.10.7) | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_504731_88202519641_IFIndAs.html` | `60bba0bba0737afac7eabbb407932e17ae9d16db4311012e9589b4aa8898382e` |

## QP4: the last BSE results inline XBRL files still INVALID_XBRL (X285-X287; files of the bse-fetch runner ledgers, unmodified, sha256 verified = ledger / vault blob)

Read by `tests/test_qp4_bse_ixbrl_repairs.py`. Kept in `bse/` so the end-to-end fixture glob and its pinned counts are
unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `bse/Integrated_Finance_Ind_As_539469_1422026194048_IFIndAs.html` | X285: Q3 FY26 consolidated (539469 Panorama Studios), OCR'd notes text block with a bare `<` ("re<lassified"): not well-formed (invalid token) | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_539469_1422026194048_IFIndAs.html` | `f3b7ca98e23ad2008c9168c83953f5b66245f113a7024fda26817cf91d279774` |
| `bse/IFOtherthan_538668_1482025163259_IFOtherthan.html` | X286: Q1 FY26 (538668) on the OtherThanBank template, segment table rows without `</tr>` before the next row (mismatched tag) | `https://www.bseindia.com/XBRLFILES/IFOtherthanDuplicateUploadDocument/IFOtherthan_538668_1482025163259_IFOtherthan.html` | `3a79de3ff9574ee059a8d101c8b143cfe97b186bafd8987e0615852a92eaa604` |
| `bse/Integrated_Finance_Ind_As_538668_141120252067_IFIndAs.html` | X287: Q2 FY26 consolidated (538668), the empty "Audit qualification" table left open before the next `<h2>` (mismatched tag) | `https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_538668_141120252067_IFIndAs.html` | `935f5a350ff068d9bfea3eb53c9204405f132296fb62cfcfc188276d6ca34134` |

## QD2: rule X293 (owners' quarter covered by the owners' own YTD takes no PAT fallback); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x293_owners_from_ytd.py`. Kept in `owners_ytd/` so the end-to-end fixture glob (`xbrl/*.xml`) and
its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `owners_ytd/INTEGRATED_FILING_INDAS_1711189_10082026062233_WEB.xml` | Lumax Auto Technologies (LUMAXTECH) Q1 FY27 consolidated results: PAT 98.6365 Cr, no ProfitOrLossAttributableToOwnersOfParent (only the comprehensive-income split) [X293] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1711189_10082026062233_WEB.xml | `1bb5ab346ddfb1378c66f37050f63beea9689db5b24f0a63d6820ad5261171af` |
| `owners_ytd/INTEGRATED_FILING_INDAS_1745364_24102026044213_WEB.xml` | LUMAXTECH Q2 FY27 consolidated results: owners' profit Q2 105.50894 Cr and H1 192.14884 Cr (the owners' YTD covering Q1) [X293] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1745364_24102026044213_WEB.xml | `9b23c2e7389d00e1e486d1e4750c2bae30ac77d5e72e02e451c5ac178d48e4fc` |

## QE: rule X300 (operating lines of a restated TTM window bridge through the YTD); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x300_operating_lines_bridge.py`. Kept in `operating_bridge/` so the end-to-end fixture glob
(`xbrl/*.xml`) and its pinned counts are unchanged. Polyplex Corporation (POLYPLEX) consolidated results, FY26 and H1 FY27.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `operating_bridge/INTEGRATED_FILING_INDAS_1510629_12082025102624_WEB.xml` | POLYPLEX Q1 FY26 consolidated results: other income 29.79 Cr (a quarter of the FY26 YTD identity) [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1510629_12082025102624_WEB.xml | `fb4d593f49c5fe91f458adcd8c788fd7b71ac2e72aa0404ae912cc25f88a8ce5` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1574410_13112025092200_WEB.xml` | POLYPLEX Q2 FY26 consolidated: Q2 other income 22.77 Cr, H1 FY26 50.08 Cr (Q1 + Q2 = 52.56) [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1574410_13112025092200_WEB.xml | `e22e2b194953721551c63356e9f5e78768390b489148b3059711273429be0334` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1625677_13022026082321_WEB.xml` | POLYPLEX Q3 FY26 consolidated: Q3 other income 27.26 Cr, 9M 70.64 Cr (quarters 79.82) [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1625677_13022026082321_WEB.xml | `15dda4fcedba16734a45b50d062d8c7cd299af04c5b95fb17b2a7e204c62090e` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1672109_23052026084256_WEB.xml` | POLYPLEX Q4 FY26 consolidated: Q4 other income 61.86 Cr, FY26 87.57 Cr (quarters 141.68); FY26 total income breaks the YTD identity (guarded tag, X106) [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1672109_23052026084256_WEB.xml | `4c7db2b28bac3f69ac2679d2a7dc5be81debf752f1f8829293265a40d8c2b0f9` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1712085_11082026071859_WEB.xml` | POLYPLEX Q1 FY27 consolidated: other income 25.47 Cr [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1712085_11082026071859_WEB.xml | `c9d27d66662e937a262c0fc41725dcc4416582e3a6221fc2c6bd847b56ee9607` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1757942_13112026085007_WEB.xml` | POLYPLEX Q2 FY27 consolidated: Q2 other income 43.59 Cr, H1 FY27 67.82 Cr (quarters 69.06) [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1757942_13112026085007_WEB.xml | `246bcd8260dd5b0a99bf68ad62fe6e14994060c41780a13d33c316642db98811` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1499085_31072025042102_WEB.xml` | Swiggy (SWIGGY) Q1 FY26 standalone results: PBT before exceptional items -991 Cr [X300 prior-year mixed basis] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1499085_31072025042102_WEB.xml | `7ad5c45c27e2a834c44cb390878a2e05ff3354d1389d6e400dad3997303e3162` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1561841_30102025063455_WEB.xml` | SWIGGY Q2 FY26 standalone: Q2 -881 Cr, H1 FY26 -1,872 Cr (= Q1 + Q2, the original basis) [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1561841_30102025063455_WEB.xml | `85c5670747913e8dc5bc2ffd8ffa6a7a09b2c604a481ada11304078c88092616` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1614516_30012026041413_WEB.xml` | SWIGGY Q3 FY26 standalone: Q3 -886 Cr, 9M -2,758 Cr [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1614516_30012026041413_WEB.xml | `ff45dd12386221263a3d505609f09728543078e71acee4fc3d3b94f114d3d32a` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1665216_09052026120920_WEB.xml` | SWIGGY Q4 FY26 standalone: Q4 279 Cr, FY26 436 Cr on the continuing basis (quarters -2,479 Cr): FY restated, H1 FY26 not [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1665216_09052026120920_WEB.xml | `91cf2d1de71eb615e6d87bb5bc1c7b1ee1f95d97e56b251eaadadb4f10c3f0e2` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1705249_30072026050331_WEB.xml` | SWIGGY Q1 FY27 standalone: 350 Cr [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1705249_30072026050331_WEB.xml | `1da2df2ea1dbb87ea6fe760c47f47cd21d299f21da03b6d17bdc4746390e7c4b` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1744174_22102026064058_WEB.xml` | SWIGGY Q2 FY27 standalone: Q2 287 Cr, H1 FY27 637 Cr [X300] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1744174_22102026064058_WEB.xml | `6b9ecaf33b10611f0ca3514c9020430605bf63ff73d0a01595791f24b0ab8bf4` |

## QE2: rule X301 (X106 guarded-tag bridge only on one basis); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x301_guarded_bridge_one_basis.py` (with the SWIGGY files of the QE section above). Kept in
`operating_bridge/` so the end-to-end fixture glob (`xbrl/*.xml`) and its pinned counts are unchanged. Patanjali Foods
(PATANJALI) standalone results, FY26 and H1 FY27 (LevelOfRounding: lakhs).

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `operating_bridge/INTEGRATED_FILING_INDAS_1513074_14082025053356_WEB.xml` | PATANJALI Q1 FY26 standalone results: revenue 8,899.71 Cr [X301] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1513074_14082025053356_WEB.xml | `e3e016926d789d643cff7412794fbf41cb8b8e3146051c849eb2d589913facd2` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1562673_31102025052557_WEB.xml` | PATANJALI Q2 FY26 standalone: Q2 revenue 9,798.84 Cr, H1 FY26 18,564.86 Cr (Q1 + Q2 = 18,698.55: the prior-year YTD breaks the identity) [X301] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1562673_31102025052557_WEB.xml | `e296f343c3e55e308aaeb9b7cda51e6b1ffa7a76d48670cbca98cb81385a423e` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1623623_11022026072616_WEB.xml` | PATANJALI Q3 FY26 standalone: Q3 10,483.71 Cr, 9M 29,013.98 Cr (quarters 29,182.26; NEXT_YTD_AGREES) [X301] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1623623_11022026072616_WEB.xml | `64b91826bbbfdb3639bbe9fc699e5b67dd7c3fc1fc18374c37f105bf71f33b5e` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1678022_30052026094755_WEB.xml` | PATANJALI Q4 FY26 standalone (re-sent results, same figures as the first): Q4 11,155.60 Cr, FY26 40,169.58 Cr (quarters 40,337.81, within 0.5 %: holds) [X301] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1678022_30052026094755_WEB.xml | `4b003f1cc8bd222d5e13a8bbd5ce3799ba9b5343d8331d3b059667a9a552649b` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1715092_14082026083859_WEB.xml` | PATANJALI Q1 FY27 standalone: revenue 11,337.45 Cr [X301] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1715092_14082026083859_WEB.xml | `ee764b0850ad9c7dc8ab4f94c22acd8a15e588acfaaa3554069f7b9758a3b885` |
| `operating_bridge/INTEGRATED_FILING_INDAS_1758226_14112026020725_WEB.xml` | PATANJALI Q2 FY27 standalone: H1 FY27 revenue 22,660.03 Cr [X301] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1758226_14112026020725_WEB.xml | `cb26c4ab5ae6224e1ad531824cc63b00cc0261ce19c4bf4a8ac32f0a05af1dfa` |

## QF4: RESTATED sub-classes CASH_EQUIVALENTS_RECLASSIFIED (X306) and FX_EFFECT_RECLASSIFIED (X307); copied 2026-11-18 from the local vault blob, gunzipped, sha256 verified

Read by `tests/test_x306_x307_cash_flow_reclassified.py`. Kept in `annual_restated/` so the end-to-end fixture glob
(`xbrl/*.xml`) and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `annual_restated/INTEGRATED_FILING_INDAS_1447925_22052025091528_WEB.xml` | Vindhya Telelinks Q4 FY25 standalone results: FY25 net cash flow -57.16 Cr, closing cash and cash equivalents 95.44 Cr, total assets 4,079.00 Cr (the stored side) [X306] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1447925_22052025091528_WEB.xml | `2e6c6344c4c89b09c1bcf040636b5cb7602b50c9d1db7e2a557fdfbf02801020` |
| `annual_restated/AR_XBRL_VINDHYATEL_01092026190709.xml` | Vindhya Telelinks FY26 standalone annual: FY25 cash and cash equivalents 85.01 Cr (other bank balances 30.02 -> 40.46 Cr) and net cash flow -67.60 Cr, total assets / equity / PAT unchanged [X306] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_VINDHYATEL_01092026190709.xml | `32a3c120c9869e8a41fa5437a9ac1bc03b751b8983e938f9de5657613f0b4abe` |
| `annual_restated/INTEGRATED_FILING_INDAS_1424269_24042025081042_WEB.xml` | Kirloskar Pneumatic Q4 FY25 consolidated results: FY25 net cash flow 13.63 Cr, effect of exchange rate changes 0.22 Cr, after it 13.85 Cr (the stored side) [X307] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_INDAS_1424269_24042025081042_WEB.xml | `922512ab95a8b9a872686fbf50ed00fa42d5dbc04ff1c8ad253706111c2f6fce` |
| `annual_restated/AR_XBRL_KIRLPNU_19082026192059.xml` | Kirloskar Pneumatic FY26 consolidated annual: FY25 net cash flow 14.07 Cr, exchange difference -0.22 Cr, after it 13.85 Cr [X307] | https://nsearchives.nseindia.com/corporate/xbrl/AR_XBRL_KIRLPNU_19082026192059.xml | `22b205d7dc05876d41f63557bb14a3fdcc237c0e26996b2a82b946b7544f9b4b` |

## QU: rights entitlements kept out of the Rs 500 Cr universe (X311); copied 2026-11-18 from the local vault blob (stored uncompressed), sha256 verified

Read by `tests/test_x311_universe_rights_entitlements.py`. The bhavcopy also joins the X140 characterisation glob
(`bhavcopy/BhavCopy_NSE_CM_*.csv.zip`): UPL-RE `INE628A20010` beside UPL `INE628A01036`, markers agree.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `pr_zip/PR061224.zip` | PR zip of 06-Dec-2024 (a Friday, week end): UPL-RE, series BE, Category Permitted, Issue Size 93,680,642 x 190.25 = Market Cap Rs 17,822,742,140.50 (>= Rs 500 Cr: admitted by rule U1-P); UPL EQ Listed Rs 422,329,389,208.65 [X311] | https://nsearchives.nseindia.com/archives/equities/bhavcopy/pr/PR061224.zip | `d01ea415887c77a22ed606bf7a5d3c96fcaf486851060d881d61e994df921124` |
| `bhavcopy/BhavCopy_NSE_CM_0_0_0_20241206_F_0000.csv.zip` | UDiFF bhavcopy of 06-Dec-2024: identity of UPL-RE (`INE628A20010`, BE) and UPL (`INE628A01036`, EQ) for the PR zip of the same day [X311] | https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_20241206_F_0000.csv.zip | `ae4eff2154d4260cbb7fa8946554eb67ae7270c5a1e62fb8cbbf8cceca1c9ed8` |

## QB9: BSE NBFC results as plain XML instances (X313; blobs of the bse-fetch runner ledger r14 of 2026-11-18, copied unmodified, sha256 verified = ledger blob)

Read by `tests/test_x313_bse_nbfc_xml.py`. Kept in `bse/` so the end-to-end fixture glob (`xbrl/*.xml`) and its
pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `bse/Integrated_Finance_NBFC_530245_1482026171926_IFNBFC.xml` | X313: Aryaman Financial Services (530245, Permitted, INE032E01017) Q1 FY27 standalone, plain XML `<!--IFNBFC V2.1 (26-06-2026)-->`, IntegratedFinance_NBFC 2026-01-31, LevelOfRounding Lakhs (smallest IFNBFC file of the ledger) | `https://www.bseindia.com/XBRLFILES/IFNBFCDuplicateUploadDocument/Integrated_Finance_NBFC_530245_1482026171926_IFNBFC.xml` | `4a28c54bfccf34b12ffbd362da1e816e4a914273fff9a489793d9e61fd2f9d8e` |
| `bse/Integrated_Finance_NBFC_530245_1482026172036_IFNBFC.xml` | X313: the same company and quarter, consolidated | `https://www.bseindia.com/XBRLFILES/IFNBFCDuplicateUploadDocument/Integrated_Finance_NBFC_530245_1482026172036_IFNBFC.xml` | `bab83ddd5dbe2fac7336ebb2cd6350bd76d597ac35a265b9635ecab7426edbe8` |
| `bse/bse_Corp_FinanceResult_ng_new_530245_flagdur6_20261118.json` | X313: the scrip's results listing (FlagDur 6) naming both files (`XMLName` / `Consol_XMLName`, `Fld_CreateDate` 2026-08-14T17:19:26.623 for JQ2026-2027) | `https://api.bseindia.com/BseIndiaAPI/api/Corp_FinanceResult_ng_new/w?SCRIP_CD=530245&FlagDur=6&HFQ=&ISUBGROUP_CODE=&segment=C` | `fbd32a3d88eaea319cc714e388381cd38473333d21a8691c3b728a33e87bc116` |

## QY3: rules NBFC_NET_LINE_SIDE (X314) and YTD_COPIES_PRIOR_YEAR (X315); copied 2026-11-19 from the local vault blob (gunzipped, or stored uncompressed), sha256 verified

Read by `tests/test_x314_x315_ytd_presentation_rules.py`. Kept in `nbfc_net_line/` and `ytd_copy/` so the
end-to-end fixture glob (`xbrl/*.xml`) and its pinned counts are unchanged.

| File | Why | Source URL | SHA-256 |
|---|---|---|---|
| `nbfc_net_line/Integrated_Finance_NBFC_543766_3172026221822_IFNBFC.xml` | Ashika Credit Capital (BSE 543766, Permitted) Q1 FY27 consolidated, IFNBFC plain XML, Lakhs: revenue 1,686,885,000, net loss on fair value changes 406,000 (in expenses) [X314] | https://www.bseindia.com/XBRLFILES/IFNBFCDuplicateUploadDocument/Integrated_Finance_NBFC_543766_3172026221822_IFNBFC.xml | `b6759dd18f13424518391e92a964993257e192c0386b016db221dc29d41e2fb5` |
| `nbfc_net_line/Integrated_Finance_NBFC_543766_31102026181525_IFNBFC.xml` | the same, Q2 / H1 FY27: Q2 revenue 634,293,000 with a net loss on fair value changes of 19,963,000 in expenses; H1 revenue 2,300,809,000 with a net gain of 1,272,402,000 and no loss line (H1 = Q1 + Q2 - 20,369,000) [X314] | https://www.bseindia.com/XBRLFILES/IFNBFCDuplicateUploadDocument/Integrated_Finance_NBFC_543766_31102026181525_IFNBFC.xml | `3d7b0a98af4412ab37d154512c5cc138637a060c20665c6ea80dee0f7c7fbee2` |
| `nbfc_net_line/INTEGRATED_FILING_NBFC_INDAS_1694707_16072026105712_WEB.xml` | PNB Gilts (NSE) Q1 FY27 standalone: revenue 4,545,599,000, net gain on fair value changes 182,320,000 [X314] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1694707_16072026105712_WEB.xml | `f1880a28bdf6ab15aa324c518ee66f9a943318af9a538034c3df989b2a646d1c` |
| `nbfc_net_line/INTEGRATED_FILING_NBFC_INDAS_1737076_13102026051135_WEB.xml` | the same, Q2 / H1 FY27: Q2 net loss on fair value changes 177,075,000 in expenses, H1 a net gain of 5,246,000; H1 revenue 8,731,680,000 = Q1 + Q2 (4,363,156,000) - 177,075,000 [X314] | https://nsearchives.nseindia.com/corporate/xbrl/INTEGRATED_FILING_NBFC_INDAS_1737076_13102026051135_WEB.xml | `9d8951edaa6a5e87d7aa2a53c9a9df57e4733bad9532a804fc48d55079158bcb` |
| `ytd_copy/Integrated_Finance_Ind_As_526173_16620251264_IFIndAs.html` | Andrew Yule (BSE 526173, Permitted) Q4 FY25 consolidated inline XBRL: FY25 revenue 3,117,097,000, total income 3,752,739,000, PBT -285,057,000, PAT -28,382,000 [X315] | https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_526173_16620251264_IFIndAs.html | `f14a5cf0e6767fdbc8b0370f80469e735348aed7b5297ae2037e61a85f2d42fb` |
| `ytd_copy/Integrated_Finance_Ind_As_526173_148202518736_IFIndAs.html` | the same, Q1 FY26 consolidated [X315] | https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_526173_148202518736_IFIndAs.html | `3c9eb27d8ecfc2f839c25a39c57772883c2024bff48ec4dccddf9ac30ae5e32f` |
| `ytd_copy/Integrated_Finance_Ind_As_526173_13112025185648_IFIndAs.html` | the same, Q2 / H1 FY26 consolidated (H1 = Q1 + Q2) [X315] | https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_526173_13112025185648_IFIndAs.html | `8ca49e8998e61d1c33f3b2f255c5ad2f3d167d10e2286ebd7f69cbdacc6d1f57` |
| `ytd_copy/Integrated_Finance_Ind_As_526173_1122026181616_IFIndAs.html` | the same, Q3 FY26 consolidated: the Apr-Dec 2025 context carries the FY25 column to the rupee (revenue, total income, total expenses 4,037,796,000, PBT, PAT) [X315] | https://www.bseindia.com/XBRLFILES/IFIndasDuplicateUploadDocument/Integrated_Finance_Ind_As_526173_1122026181616_IFIndAs.html | `7db19c7f5de7a49f69e7f3e6703592bf345e74be77b483cc1457934e96d1fc5d` |
