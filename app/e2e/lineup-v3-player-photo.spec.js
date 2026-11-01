import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";

const base=JSON.parse(readFileSync(new URL("../../football/data/dashboard.json",import.meta.url),"utf8"));
const original=base.matches.find(x=>!x.finished&&Array.isArray(x.probs))||base.matches[0];
const positions=["POR","LI","DFC","DFC","LD","MCD","MC","MP","EI","DC","ED"];
const local=["Portero","Lateral Izquierdo","Central Uno","Central Dos","Lateral Derecho",
  "Medio Defensivo","Medio Centro","Álex García","Extremo I","Delantero","Extremo D"];
const away=local.map((p,i)=>"Visitante "+i+" "+p);
function makeFeed({broken=false,withoutPositions=false}={}){
 const feed=structuredClone(base),target=feed.matches.find(x=>x.id===original.id);
 target.alineacion={
  status:"confirmado",provider:"API-Football",
  local:broken?[...local.slice(0,10),"Portero"]:local,
  visitante:away, posiciones_local:withoutPositions?[]:positions,
  posiciones_visitante:withoutPositions?[]:positions,
  clave_local:[],clave_visitante:[],best_props:[],
 };
 feed.players={laliga:{label:"LaLiga",players:[{
  player:"Álex García",team:target.home,position:"Attacker",source:"API-Football",
  profile:{photo:"https://media.api-sports.io/football/players/1234.png",nationality:"España",age:24}
 }]}};
 return{feed,target};
}
async function openMatch(page,target,feed) {
 await page.route("**/dashboard.json*",r=>r.fulfill({
  status:200,contentType:"application/json",body:JSON.stringify(feed)}));
 await page.route("https://media.api-sports.io/**",r=>r.fulfill({
  contentType:"image/png",
  body:Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAFUlEQVR4nGN0O7HgPwMDAwMTAxQAACiuArEc0XZZAAAAAElFTkSuQmCC","base64")
 }));
 await page.goto("/");
 if((page.viewportSize()?.width||1000)<=860)await page.getByRole("button",{name:"Abrir menú"}).click();
 await page.locator(".snav").getByRole("button",{name:"Partidos",exact:true}).click();
 const row=page.locator('tr[role="button"]').filter({hasText:target.home}).filter({hasText:target.away}).first();
 await row.click();
}
test("XI valid: pitch, positions, authentic photo and profile back navigation",async({page},info)=>{
 const {feed,target}=makeFeed();
 await openMatch(page,target,feed);
 const board=page.getByTestId("lineup-board");
 await expect(board).toBeVisible();
 await expect(board.getByText("XI oficial")).toBeVisible();
 await expect(board.locator("..").getByText("0",{exact:true})).toHaveCount(0);
 await expect(board.locator("..").getByText("Alineaciones · XI oficial")).toHaveCount(0);
 await expect(board.locator(".lineup-v3-half.home .lineup-v3-slot")).toHaveCount(11);
 await expect(board.locator(".lineup-v3-half.away .lineup-v3-slot")).toHaveCount(11);
 await expect(board.locator(".lineup-v3-half.home .edge-player-avatar img")).toHaveCount(1);
 const portrait=board.locator(".lineup-v3-half.home .edge-player-avatar img");
 await portrait.scrollIntoViewIfNeeded(); // loading="lazy" on mobile
 await expect(portrait).toHaveJSProperty("naturalWidth",2);
 await board.getByRole("button",{name:`Ver ficha de Álex García, ${target.home}`}).click();
 const profile=page.getByTestId("player-profile");
 await expect(profile).toBeVisible();
 await expect(profile.getByRole("heading",{name:"Álex García"})).toBeVisible();
 await profile.getByRole("button",{name:"← Volver"}).click();
 await expect(board).toBeVisible();
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
 expect(overflow).toBeLessThanOrEqual(1);
 await info.attach("lineup-v3-"+info.project.name,{body:await page.screenshot({fullPage:true,animations:"disabled"}),contentType:"image/png"});
});
test("invalid XI is not presented as official and unknown positions never invent pitch slots",async({page})=>{
 const {feed,target}=makeFeed({broken:true,withoutPositions:true});
 await openMatch(page,target,feed);
 const board=page.getByTestId("lineup-board");
 await expect(board).toBeVisible();
 await expect(board.getByText("XI oficial")).toHaveCount(0);
 await expect(board.locator(".lineup-v3-half.home .lineup-v3-list")).toBeVisible();
 await expect(board.getByText("Se han omitido nombres duplicados hasta verificar los datos.")).toBeVisible();
 await expect(board.getByText(/Alineación incompleta/)).toBeVisible();
 await expect(board.locator(".lineup-v3-half.home .lineup-v3-row")).toHaveCount(0);
});
