import test from "node:test";
import assert from "node:assert/strict";
import catalog from "./verifiedPlayerMedia.js";
import { licensedPhotoRecord,photoCreditForPlayer,photoForPlayer } from "./mediaIdentity.js";

const licensed={
 player:"Lamine Yamal",teams:["FC Barcelona","Barcelona"],
 wikidata_qid:"Q113704154",
 image_url:"https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/a.jpg",
 source_url:"https://commons.wikimedia.org/wiki/File:Lamine_Yamal_photo.jpg",
 license:"CC BY-SA 4.0",
 license_url:"https://creativecommons.org/licenses/by-sa/4.0/",
 author:"Bryan Berlin",modifications:"Miniatura"
};
test("photo catalog uses exact full player identity and approved team aliases only",()=>{
 catalog.entries.push(licensed);
 try{
  assert.equal(photoForPlayer({player:"Lamine Yamal",team:"Barcelona"}),licensed.image_url);
  assert.equal(photoForPlayer({player:"Lamine Yamal",team:"FC Barcelona"}),licensed.image_url);
  assert.equal(photoForPlayer({player:"Yamal",team:"FC Barcelona"}),null);
  assert.equal(photoForPlayer({player:"Lamine Yamal",team:"Real Madrid"}),null);
  assert.equal(photoCreditForPlayer({player:"Lamine Yamal",team:"Barcelona"}).author,"Bryan Berlin");
 }finally{catalog.entries.pop();}
});
test("unverifiable license and duplicated matching records never display",()=>{
 catalog.entries.push({...licensed,license_url:"https://evil.org/not-a-license"});
 try{
  assert.equal(licensedPhotoRecord({player:"Lamine Yamal",team:"Barcelona"}),null);
 }finally{catalog.entries.pop();}
 catalog.entries.push(licensed,{...licensed});
 try{
  assert.equal(licensedPhotoRecord({player:"Lamine Yamal",team:"Barcelona"}),null);
 }finally{catalog.entries.pop();catalog.entries.pop();}
});
