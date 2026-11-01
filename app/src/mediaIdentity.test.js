import test from "node:test";import assert from "node:assert/strict";
import { safePlayerPhoto, photoForPlayer, initials } from "./mediaIdentity.js";
test("safe media URLs reject tracking, scripts, credentials or arbitrary hosts",()=>{
 assert.equal(safePlayerPhoto("javascript:alert(1)"),null);
 assert.equal(safePlayerPhoto("https://example.org/a.jpg"),null);
 assert.equal(safePlayerPhoto("https://upload.wikimedia.org.fake.com/x.jpg"),null);
 assert.equal(safePlayerPhoto("http://media.api-sports.io/football/players/1.png"),null);
 assert.equal(safePlayerPhoto("https://a:b@upload.wikimedia.org/1.png"),null);
 assert.equal(safePlayerPhoto("https://upload.wikimedia.org/wikipedia/commons/a/b/c.jpg"),"https://upload.wikimedia.org/wikipedia/commons/a/b/c.jpg");
 assert.equal(photoForPlayer({profile:{photo:"https://media.api-sports.io/football/players/1.png"}}),
 "https://media.api-sports.io/football/players/1.png");
 assert.equal(initials("Álex García"),"ÁG");
 assert.equal(initials(null),"?");
});
