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
| `xbrl/SHP_1740148_16102026052137_WEB.xml` | B8: Vedanta 2026-09-30. NDU + other encumbrance, no pledge (SHP10); EBT in NPNP | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1740148_16102026052137_WEB.xml` | `e1f98ab9a4db78a1b21f2e7b9f90d9cfd7e47e5fd5ec72e9525a9e0630d5eda5` |
| `xbrl/SHP_1743210_21102026055808_WEB.xml` | B8: JSW Steel 2026-09-30. Promoter pledge 12.25%; FDI (JFE) 15% (SHP10, SHP13) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1743210_21102026055808_WEB.xml` | `5a53b46441c60727a6a855b78aeed0a68921201b32ec8661daf86e58541f6bd0` |
| `xbrl/SHP_1733654_07102026112959_WEB.xml` | B8: Apollo Hospitals 2026-09-30. Promoter pledge 2.91%; >1% public holders (SHP10, SHP12) | `https://nsearchives.nseindia.com/corporate/xbrl/SHP_1733654_07102026112959_WEB.xml` | `4686100c7f9c77b5491aa1576e9a4be3a4d8ddcc988caa05ea628a0615ea0228` |

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
