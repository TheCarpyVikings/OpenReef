import { assert, makePanel, runTests, test } from "./_panel_harness.mjs";

function setup(panel) {
  const jars = {
    main: { name: "Nanno Main", species: "nanno", salinityPpt: 35, bottleProductId: "home_phyto_main" },
    backup: { name: "Nanno Backup", species: "nanno", salinityPpt: 35, bottleProductId: "home_phyto_backup" },
  };
  const products = {
    home_phyto_main: { name: "Home phyto (Nanno Main)", category: "phyto", bottleMl: 2500, remainingMl: 600, doseMl: 100, doseEveryDays: 1 },
    home_phyto_backup: { name: "Home phyto (Nanno Backup)", category: "phyto", bottleMl: 1000, remainingMl: 1000, doseMl: 35, doseEveryDays: 1 },
  };
  panel._config = { nps: { cultures: { enabled: true, jars } }, consumables: { products } };
  panel._cultures = { demo: false };
  panel._nps = {};
  panel._render = () => {};
  panel._culturesLoadSummary = async () => {};
  panel._npsLoadSummary = async () => {};
  return { jars, products };
}

test("sharing previews the combined stock and the destination plan", async () => {
  const panel = await makePanel();
  const { jars, products } = setup(panel);
  const html = panel._culturesSharedStockControls("backup", jars.backup, products);
  assert(html.includes("1600 / 2500 ml") && html.includes("100 ml dose · every day"));
  assert(html.includes('data-action="cultures-share-bottle" data-id="backup" data-target="main"'));
  assert(!html.includes("disabled"));
  const reverse = panel._culturesSharedStockControls("main", jars.main, products);
  assert(reverse.includes("Increase the destination capacity first") && reverse.includes("disabled"));
});

test("sharing excludes different salinity and already shared stocks", async () => {
  const panel = await makePanel();
  const { jars, products } = setup(panel);
  jars.main.salinityPpt = 27;
  assert(!panel._culturesSharedStockControls("backup", jars.backup, products).includes('data-action="cultures-share-bottle"'));
  jars.main.salinityPpt = 35;
  jars.backup.bottleProductId = "home_phyto_main";
  const html = panel._culturesSharedStockControls("backup", jars.backup, products);
  assert(html.includes("Shared fridge stock") && html.includes("Nanno Main + Nanno Backup"));
  assert(!html.includes('data-action="cultures-share-bottle"'));
});

test("sharing uses the returned config and refreshes both summaries", async () => {
  const panel = await makePanel();
  setup(panel);
  const merged = structuredClone(panel._config);
  merged.nps.cultures.jars.backup.bottleProductId = "home_phyto_main";
  merged.consumables.products.home_phyto_main.remainingMl = 1600;
  delete merged.consumables.products.home_phyto_backup;
  const calls = [];
  panel._callWS = async (msg) => { calls.push(msg); return { config: merged }; };
  panel._culturesLoadSummary = async () => calls.push("cultures");
  panel._npsLoadSummary = async () => calls.push("shelf");
  await panel._culturesShareBottle("backup", "main");
  assert(calls[0].type === "openreef/cultures_share_bottle" && calls[0].target_jar_id === "main");
  assert(calls.includes("cultures") && calls.includes("shelf"));
  assert(panel._config === merged && panel._culturesShareNotice.text.includes("Stock combined"));
  assert(!panel._busy);
});

test("dirty settings and demo mode prevent merging and refusals preserve config", async () => {
  const panel = await makePanel();
  setup(panel);
  let calls = 0;
  panel._callWS = async () => { calls++; throw new Error("Stock has changed; capacity exceeded"); };
  panel._configDirty = true;
  await panel._culturesShareBottle("backup", "main");
  assert(calls === 0 && panel._culturesShareNotice.text.includes("Save your Settings"));
  panel._configDirty = false;
  panel._cultures.demo = true;
  await panel._culturesShareBottle("backup", "main");
  assert(calls === 0);
  panel._cultures.demo = false;
  const before = JSON.stringify(panel._config);
  await panel._culturesShareBottle("backup", "main");
  assert(calls === 1 && panel._culturesShareNotice.error && panel._culturesShareNotice.text.includes("capacity exceeded"));
  assert(JSON.stringify(panel._config) === before && !panel._busy);
});

test("the shelf identifies both suppliers on one stock card", async () => {
  const panel = await makePanel();
  const { products } = setup(panel);
  const html = panel._npsProductCard("home_phyto_main", products.home_phyto_main,
    { remainingMl: 1600, bottleMl: 2500, cultureNames: ["Nanno Main", "Nanno Backup"], handDose: {} });
  assert(html.includes("Shared harvest stock · Nanno Main + Nanno Backup"));
});

await runTests();
