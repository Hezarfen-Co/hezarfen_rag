---
course: MAT101
title: Türev — Giriş
topic: türev
author_role: teacher
author: ogretmen1
---

# Türev — Giriş

Türev, bir fonksiyonun **anlık değişim oranını** ölçer. Geometrik olarak, bir
noktadaki türev o noktadan geçen **teğet doğrunun eğimidir**.

## Tanım (limit ile)
Bir f fonksiyonunun x noktasındaki türevi:

f'(x) = lim (h → 0) [ f(x + h) − f(x) ] / h

Bu limit varsa fonksiyon o noktada **türevlenebilir** denir. Türevlenebilen her
fonksiyon süreklidir; ancak sürekli olan her fonksiyon türevlenebilir olmak
zorunda değildir (örneğin f(x) = |x| fonksiyonu x = 0'da süreklidir ama
türevlenemez, çünkü sağ ve sol eğimler farklıdır).

## Temel kurallar
- **Sabit:** (c)' = 0
- **Kuvvet kuralı:** (xⁿ)' = n·xⁿ⁻¹
- **Toplam:** (f + g)' = f' + g'
- **Çarpım:** (f·g)' = f'·g + f·g'
- **Bölüm:** (f/g)' = (f'·g − f·g') / g²
- **Zincir kuralı:** (f(g(x)))' = f'(g(x))·g'(x)

## Örnekler
1. f(x) = x² → f'(x) = 2x. x = 3 noktasında teğetin eğimi f'(3) = 6'dır.
2. f(x) = 3x⁴ − 5x + 2 → f'(x) = 12x³ − 5.
3. f(x) = (2x + 1)³ → zincir kuralıyla f'(x) = 3(2x + 1)²·2 = 6(2x + 1)².

## Uygulama: hız ve ivme
Konum fonksiyonu s(t) ise, **hız** v(t) = s'(t), **ivme** a(t) = v'(t) = s''(t)'dir.
Örneğin s(t) = 5t² için hız v(t) = 10t, ivme a(t) = 10 (sabit) olur.

## Özet
Türev = anlık değişim = teğet eğimi. Kuvvet, çarpım, bölüm ve zincir kuralları
en sık kullanılan araçlardır. Fizikte hareket, ekonomide marjinal analiz gibi
alanlarda temeldir.
