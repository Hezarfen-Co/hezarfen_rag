---
course: MAT101
title: Limit — Özet
topic: limit
author_role: teacher
author: ogretmen1
---

# Limit — Özet

**Limit**, bir fonksiyonun girişi bir değere yaklaşırken çıkışının hangi değere
yaklaştığını anlatır. x, a'ya yaklaşırken f(x)'in L'ye yaklaşmasını şöyle yazarız:

lim (x → a) f(x) = L

Önemli nokta: limit, fonksiyonun a noktasındaki **değeriyle** değil, a'ya
**yaklaşırkenki davranışıyla** ilgilenir. f(a) tanımsız olsa bile limit var olabilir.

## Tek yönlü limitler
- Soldan limit: lim (x → a⁻) f(x)
- Sağdan limit: lim (x → a⁺) f(x)

İki yönlü limit ancak soldan ve sağdan limitler **eşitse** vardır.

## Limit kuralları
- Toplam/fark: lim(f ± g) = lim f ± lim g
- Çarpım: lim(f·g) = lim f · lim g
- Bölüm: lim(f/g) = lim f / lim g  (payda limiti ≠ 0 ise)

## Belirsiz durumlar
0/0, ∞/∞, ∞−∞ gibi ifadeler **belirsizdir**; doğrudan hesaplanamaz. Yöntemler:
- **Çarpanlara ayırma:** lim (x→2) (x²−4)/(x−2) = lim (x+2) = 4.
- **Eşlenikle genişletme:** kök içeren ifadelerde.
- **L'Hôpital kuralı:** 0/0 veya ∞/∞ durumunda pay ve paydanın türevini al.

## Süreklilik
f fonksiyonu a noktasında sürekliyse üç koşul sağlanır:
1. f(a) tanımlıdır,
2. lim (x → a) f(x) vardır,
3. lim (x → a) f(x) = f(a).

## Özet
Limit, türev ve integralin temelidir. Belirsiz durumlarda çarpanlara ayırma,
eşlenik veya L'Hôpital kullanılır. Süreklilik, limitin fonksiyon değerine eşit
olmasıdır.
