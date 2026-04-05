function calc_power_flow(
    V1_mag, V1_angle,
    V2_mag, V2_angle,
    r, x,
    b_from, b_to
)

    V1 = V1_mag * cis(V1_angle)
    V2 = V2_mag * cis(V2_angle)

    Z = complex(r, x)
    Y = 1 / Z

    Ysh_from = complex(0, b_from)
    Ysh_to = complex(0, b_to)

    I12 = Y * (V1 - V2) + Ysh_from * V1
    I21 = Y * (V2 - V1) + Ysh_to * V2

    S12 = V1 * conj(I12)
    S21 = V2 * conj(I21)
    Sloss = S12 + S21

    return Dict(
        "P_12" => real(S12),
        "Q_12" => imag(S12),
        "P_21" => real(S21),
        "Q_21" => imag(S21),
        "Loss_P" => real(Sloss),
        "Loss_Q" => imag(Sloss)
    )
end
