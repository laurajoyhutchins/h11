import Init

namespace HexPreservation

/-- The reverse-after-append nibble loop, expressed in most-significant-first
    order. This models candidate Python's bitwise-and, shift-right, and
    reversal for arbitrary natural numbers. -/
def bitwiseDigits (n : Nat) : List Char :=
  if h : n = 0 then []
  else bitwiseDigits (n >>> 4) ++ [(n &&& 15).digitChar]
termination_by n
decreasing_by
  rw [Nat.shiftRight_eq_div_pow]
  exact Nat.div_lt_self (Nat.pos_of_ne_zero h) (by decide)

theorem lowNibble (n : Nat) : n &&& 15 = n % 16 := by
  simpa using Nat.and_two_pow_sub_one_eq_mod n 4

theorem highNibbles (n : Nat) : n >>> 4 = n / 16 := by
  simp [Nat.shiftRight_eq_div_pow]

theorem bitwiseDigits_zero : bitwiseDigits 0 = [] := by
  simp [bitwiseDigits]

theorem bitwiseDigits_eq_toDigits (n : Nat) (hn : 0 < n) :
    bitwiseDigits n = Nat.toDigits 16 n := by
  induction n using Nat.strongRecOn with
  | ind n ih =>
    have hne : n ≠ 0 := Nat.ne_of_gt hn
    rw [bitwiseDigits]
    simp only [dite_eq_right hne]
    by_cases small : n < 16
    · have q : n >>> 4 = 0 := by
        rw [highNibbles]
        omega
      rw [q, bitwiseDigits_zero]
      simp only [List.nil_append]
      rw [lowNibble, Nat.mod_eq_of_lt small, Nat.toDigits_of_lt_base small]
    · have hlarge : 16 ≤ n := by omega
      have hq : 0 < n >>> 4 := by
        rw [highNibbles]
        omega
      have hlt : n >>> 4 < n := by
        rw [highNibbles]
        exact Nat.div_lt_self hn (by decide)
      rw [ih (n >>> 4) hlt hq]
      rw [lowNibble, highNibbles]
      exact (Nat.toDigits_of_base_le (by decide : 1 < 16) hlarge).symm

-- Each List item models a separate writer-callback invocation. This is
-- stronger than equal concatenated wire bytes.
def asciiBytes (chars : List Char) : List UInt8 :=
  chars.map (fun c => UInt8.ofNat c.toNat)

def baselineChunk (data : List UInt8) : List (List UInt8) :=
  if data.isEmpty then []
  else [asciiBytes (Nat.toDigits 16 data.length) ++ [13, 10], data, [13, 10]]

def candidateChunk (data : List UInt8) : List (List UInt8) :=
  if data.isEmpty then []
  else [asciiBytes (bitwiseDigits data.length) ++ [13, 10], data, [13, 10]]

theorem chunkTrace_eq_for_all_payloads (payload : List UInt8) :
    candidateChunk payload = baselineChunk payload := by
  unfold candidateChunk baselineChunk
  by_cases h : payload.isEmpty
  · simp [h]
  · have hp : 0 < payload.length := by
      cases payload with
      | nil => simp at h
      | cons hd tl => simp
    simp only [h]
    rw [bitwiseDigits_eq_toDigits payload.length hp]

-- Ending represents arbitrary but unchanged end-of-message callback writes
-- including trailers; the unchanged header writer is a source premise.
def baselineMessage (parts : List (List UInt8)) (ending : List (List UInt8)) :
    List (List UInt8) :=
  parts.flatMap baselineChunk ++ [[48, 13, 10]] ++ ending

def candidateMessage (parts : List (List UInt8)) (ending : List (List UInt8)) :
    List (List UInt8) :=
  parts.flatMap candidateChunk ++ [[48, 13, 10]] ++ ending

theorem messageTrace_eq_for_all_inputs
    (parts : List (List UInt8)) (ending : List (List UInt8)) :
    candidateMessage parts ending = baselineMessage parts ending := by
  have h : candidateChunk = baselineChunk := by
    funext data
    exact chunkTrace_eq_for_all_payloads data
  simp [candidateMessage, baselineMessage, h]

end HexPreservation

#print axioms HexPreservation.bitwiseDigits_eq_toDigits
#print axioms HexPreservation.chunkTrace_eq_for_all_payloads
#print axioms HexPreservation.messageTrace_eq_for_all_inputs
