/** Un nombre entre 1 et `faces`, comme un dé. `aleatoire` sert aux tests. */
export function lancer(faces: number, aleatoire: () => number = Math.random): number {
  if (!Number.isInteger(faces) || faces < 2) throw new RangeError("il faut au moins deux faces");
  return Math.floor(aleatoire() * faces) + 1;
}
