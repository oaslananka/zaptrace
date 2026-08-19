# ZapTrace Safety Policy

> **⚠️ ELECTRONICS DESIGN IS INHERENTLY RISKY.**
> **ZapTrace is pre-1.0 software. All outputs require human review.**

## Scope of Safety Concerns

### Design Errors
ZapTrace can generate designs that, if fabricated, could cause:
- **Fire**: Incorrect trace widths, under-rated components, thermal issues
- **Thermal damage**: Overheating components, insufficient copper
- **Equipment damage**: Incorrect voltage/current paths
- **Electric shock**: Inadequate clearance/creepage for high-voltage designs
- **Radio interference**: Legal liability from unlicensed emissions
- **Complete system failure**: Logic errors, incorrect connections
- **Battery hazards**: LiPo/Li-ion charging without proper protection

### Validation Limitations
- **ERC (Electrical Rule Checking)**: Checks connectivity and basic electrical rules. Does NOT verify circuit functionality.
- **DRC (Design Rule Checking)**: Checks physical manufacturing rules. Does NOT verify electrical performance.
- **Neither ERC nor DRC** can detect:
  - Logic/firmware errors
  - Analog circuit instability
  - Signal integrity problems
  - Thermal issues
  - Mechanical fit problems
  - Regulatory compliance issues

## Your Responsibilities

### Before Fabrication
1. **Review the schematic** — Check every connection against your requirements
2. **Review the layout** — Verify placement, routing, clearance, and stackup
3. **Verify the BOM** — Check MPNs, values, ratings, and stock status
4. **Run ERC + DRC** — Review all warnings and errors
5. **Check the proof pack** — Verify reproducibility information
6. **Get a human review** — Have a qualified engineer review the design
7. **Start with a prototype run** — Never go straight to production

### If You Are Not an Electrical Engineer
**Consult one.** PCB fabrication is not forgiving of mistakes. A single error can destroy a batch of boards and connected equipment.

## What ZapTrace Does to Help

- **ERC**: 8 rules checking pin compatibility, connectivity, power nets
- **DRC**: 9 rules checking trace width, clearance, hole size, annular ring
- **Proof packs**: Audit trail of what was generated and validated
- **Warnings**: All violations are surfaced with actionable messages
- **Documentation**: We explain what each check does and doesn't cover

## Disclaimers

> ZAPTRACE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
> THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.
>
> PCB FABRICATION AND ELECTRONICS DESIGN CARRY INHERENT RISKS. THE OUTPUTS OF
> THIS SOFTWARE ARE NOT GUARANTEED TO BE ERROR-FREE, FABRICATION-READY, OR SAFE.
> ALWAYS HAVE DESIGNS REVIEWED BY A QUALIFIED ELECTRICAL ENGINEER BEFORE
> FABRICATION OR USE.

## Reporting Safety Issues

If you discover a safety-relevant bug in ZapTrace (e.g., an ERC rule that fails to catch a dangerous condition), please report it via our security policy in `SECURITY.md`.

## Best Practices

1. **Version control your designs** — Keep design files in Git
2. **Use proof packs** — Save them for every design revision
3. **Document your review** — Note what was checked and by whom
4. **Fabricate prototypes** — Never go from software to production directly
5. **Test prototypes thoroughly** — Before full production
