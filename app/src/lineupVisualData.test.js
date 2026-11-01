import test from "node:test";
import assert from "node:assert/strict";
import { analyseLineup, confirmedLineup, lineupPlayerRecord, positionCode } from "./lineupVisualData.js";

const xi=["Portero","Lateral I","Central 1","Central 2","Lateral D",
 "MCD","MC","MP","Extremo I","Delantero","Extremo D"];
const pos=["POR","LI","DFC","DFC","LD","MCD","MC","MP","EI","DC","ED"];
test("valid XI makes four ordered pitch lines without guessing",()=>{
 const out=analyseLineup(xi,pos);
 assert.equal(out.full,true);assert.equal(out.canPlot,true);
 assert.deepEqual(out.rows.map(r=>r.length),[1,4,3,3]);
 assert.equal(out.rows[1][0].position,"LI");
 assert.equal(out.rows[1].at(-1).position,"LD");
});
test("unpositioned real XI may be official but must remain a list",()=>{
 assert.equal(confirmedLineup({status:"confirmado",local:xi,visitante:xi}),true);
 assert.equal(analyseLineup(xi).canPlot,false);
});
test("duplicate and partial XI must not be called official",()=>{
 assert.equal(analyseLineup([...xi.slice(0,-1),"Portero"],pos).full,false);
 assert.equal(confirmedLineup({status:"confirmado",local:xi,visitante:xi.slice(0,10)}),false);
 assert.equal(analyseLineup(xi.slice(0,10),pos.slice(0,10)).canPlot,false);
});
test("ambiguous or missing positions don't invent tactical positions",()=>{
 const out=analyseLineup(xi,pos.map((p,i)=>i===1?"Misterio":p));
 assert.equal(out.full,true);assert.equal(out.canPlot,false);
 assert.equal(positionCode("left back"),"LI");
 assert.equal(positionCode("left winger"),"EI");
 assert.equal(positionCode("other"),null);
});
test("photo/profile records resolve only when complete name, club and uniqueness match",()=>{
 const p={player:"Álex García",team:"Girona FC",profile:{photo:"https://upload.wikimedia.org/example.jpg"}};
 const data={laliga:{players:[p]}};
 assert.equal(lineupPlayerRecord(data,"Alex Garcia","Girona"),p);
 assert.equal(lineupPlayerRecord(data,"García","Girona"),null);
 assert.equal(lineupPlayerRecord(data,"Alex Garcia","Sevilla"),null);
 assert.equal(lineupPlayerRecord({laliga:{players:[p,{...p} ]}},"Alex Garcia","Girona"),null);
});
